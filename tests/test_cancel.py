"""Stopping a turn: who says it stopped, and what the model is left holding.

`Backend.cancel` used to swallow every failure and answer False, and `Agent.cancel` passed that
answer straight through. Since `cancel` was a litert-only method, Stop reported "not running" about
every hosted turn that was running, having already released the approval it was waiting on.
"""
from ramabana.testing import fake_agent


def test_stopping_returns_the_run_state():
    a, be = fake_agent(replies=['done'])
    assert a.cancel()['state'] == 'idle'
    run = a._new_run('hello')
    run.start(be)
    assert a.cancel(run.id)['state'] == 'detached'


def test_the_stop_reaches_the_backend_rather_than_being_swallowed():
    a, be = fake_agent(replies=['done'])
    run = a._new_run('hello')
    run.start(be)
    a.cancel(run.id)
    assert be.cancelled, 'the backend was never asked'


def _bare_backend(chat):
    "A `Backend` holding `chat`, to exercise `Backend.cancel` itself rather than a double\'s override."
    from ramabana.runtime import Backend
    from ramabana.testing import SPEC
    be = Backend(SPEC)
    be.chat = chat
    return be


def test_a_backend_with_no_chat_reports_that_nothing_stopped():
    assert _bare_backend(None).cancel() is False


def test_a_backend_whose_chat_cannot_be_stopped_says_so_instead_of_lying():
    "The one case worth answering False for, and it is worth a problem the user can read."
    class NoCancel: pass
    be = _bare_backend(NoCancel())
    assert be.cancel() is False
    assert any('cannot be stopped' in p for p in be.problems)


def test_a_backend_forwards_the_stop_to_a_chat_that_has_one():
    class Chat:
        stopped = False
        def cancel(self): Chat.stopped = True
    be = _bare_backend(Chat())
    assert be.cancel() is True and Chat.stopped


def test_stopping_releases_whatever_the_turn_was_waiting_on():
    "A stop that leaves a worker parked on an approval has not stopped anything."
    import threading, time
    from ramabana import agent
    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    a, be = fake_agent(replies=['done'], approvals=ap)
    run = a._new_run('edit')
    run.start(be)
    threading.Thread(target=lambda: (time.sleep(0.05), a.cancel(run.id)), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'x'}}})
    stop()
    assert not d and 'cancelled' in d.reply()


def _delegate_race_once():
    "One cancelled `delegate_many`, returning how many children it spawned and stopped."
    import threading, time
    from fastcore.basics import AttrDict
    from ramabana.runtime import Run
    from ramabana.tools import delegate_many

    class _Sub:
        max_steps = 0
        def __init__(self, owner): self.owner, self.release = owner, threading.Event()
        def send(self, q, run=None): self.owner.started.append(q); self.release.wait(); return 'late'
        def cancel(self): self.owner.cancelled += 1; self.release.set(); return True
        def close(self): pass

    class _Parent:
        def __init__(self):
            self.spec = AttrDict(name='fake-child', local=False)
            self.started, self.spawned, self.cancelled = [], 0, 0
        def spawn(self, **kw): self.spawned += 1; return _Sub(self)

    be, parent, box = _Parent(), Run('run_parent', grace=.03), []
    parent.start()
    t = threading.Thread(target=lambda: box.extend(
        delegate_many(be, ['a', 'b', 'c'], n_workers=1, parent=parent)), daemon=True)
    t.start()
    while not be.started: time.sleep(.001)
    parent.cancel(); t.join(2.0)      # generous, so `box` is really populated and the check is real
    return be.spawned, be.cancelled, list(box)


def test_a_cancelled_run_starts_no_further_children():
    """Cancelling used to mark and stop each child in one pass.

    Stopping the first child's backend releases the worker blocked on it, and with one worker that
    worker immediately takes the next queued child -- which the pass has not marked yet, so it
    starts. About one run in six spawned two sub-agents after the cancel, and some spawned all three.
    """
    runs = [_delegate_race_once() for _ in range(40)]
    assert [(a, b) for a, b, _ in runs] == [(1, 1)] * 40


def test_cancelling_marks_every_child_before_it_stops_any_backend():
    "The invariant behind it: marking is one pass, and stopping is the pass after."
    from ramabana.runtime import Run

    class _Be:
        def cancel(self): return True

    parent = Run('p')
    parent.start()
    kids = [parent.child(str(i)) for i in range(3)]
    for k in kids: k.start(_Be())
    stopped = parent._mark_cancel()
    assert all(k.cancelled for k in kids)
    assert len(stopped) == 3


def test_cancelling_a_run_that_never_started_still_marks_its_children():
    "The pending branch finished itself and returned, leaving anything below it running."
    from ramabana.runtime import Run
    parent = Run('p')                       # never started, so still pending
    kids = [parent.child(str(i)) for i in range(2)]
    for k in kids: k.start()
    parent.request_cancel()
    assert parent.cancelled and all(k.cancelled for k in kids)


def test_a_stopped_delegation_answers_in_text_not_as_a_run_dict():
    """Every cancelled path out of `delegate` used to return `run.dict()`.

    `delegate_search` passes whatever comes back straight to `clip`, which does `str(s)`, so a
    cancelled fan-out reached the model as a stringified Python dict of run ids and timestamps
    rather than a sentence saying it had been stopped.
    """
    import threading, time
    from fastcore.basics import AttrDict
    from ramabana.runtime import Run
    from ramabana.tools import delegate, delegate_many

    class _Sub:
        max_steps = 0
        def __init__(self, owner): self.owner, self.release = owner, threading.Event()
        def send(self, q, run=None): self.owner.started.append(q); self.release.wait(); return 'late'
        def cancel(self): self.release.set(); return True
        def close(self): pass

    class _Parent:
        def __init__(self):
            self.spec = AttrDict(name='fake-child', local=False)
            self.started = []
        def spawn(self, **kw): return _Sub(self)

    # a child cancelled before it ever started
    be, parent = _Parent(), Run('run_parent', grace=.03)
    parent.start()
    child = parent.child('q')
    child.request_cancel()
    stopped = delegate(be, 'q', tools=[], run=child)
    assert isinstance(stopped, str) and "'state':" not in stopped, stopped

    # and a fan-out cancelled while its first child was in flight
    be, parent, box = _Parent(), Run('run_parent2', grace=.03), []
    parent.start()
    t = threading.Thread(target=lambda: box.extend(
        delegate_many(be, ['a', 'b', 'c'], n_workers=1, parent=parent)), daemon=True)
    t.start()
    while not be.started: time.sleep(.001)
    parent.cancel(); t.join(.5)
    assert box and all(isinstance(answer, str) for answer in box), box
    assert not any("'state':" in answer for answer in box), box

