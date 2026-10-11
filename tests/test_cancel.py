"""Stopping a turn: who says it stopped, and what the model is left holding.

`Backend.cancel` used to swallow every failure and answer False, and `Agent.cancel` passed that
answer straight through. Since `cancel` was a litert-only method, Stop reported "not running" about
every hosted turn that was running, having already released the approval it was waiting on.
"""
from ramabana.testing import fake_agent


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


# narration reaches the notebook log


def _logged_turn(agent, cancel_at=None, prompt='go'):
    "Run one turn on a real `Ui`; the assistant text its log got, one string per log cell. `cancel_at` cancels the task once it is true of the Ui."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui, run_turn
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    logged = []
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.log_cell = lambda source, outputs=None, cell_type='code': logged.append(source)
        task = asyncio.ensure_future(run_turn(u, prompt))
        if cancel_at is not None:
            for _ in range(200):
                await asyncio.sleep(.02)
                if cancel_at(u): break
            task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    try: asyncio.run(go())
    finally: tty.close()
    return [s for s in logged if s.startswith('**assistant**')]


def _scripted_agent(*steps):
    from ramabana.testing import ScriptedBackend
    a, _ = fake_agent()
    be = ScriptedBackend(steps=list(steps), token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    return a


def test_narration_before_a_tool_call_reaches_the_notebook_log():
    "The log kept only the text after the last call: `_close_seg` reset what it read."
    from ramabana.testing import Step
    a = _scripted_agent(Step('first I will look'), Step(tool=('view_file', {'path': '/proj/a.py'})), Step('and the answer'))
    (cell,) = _logged_turn(a)
    assert 'first I will look' in cell and 'and the answer' in cell
    assert cell.index('first I will look') < cell.index('and the answer')


def test_a_cancelled_turn_still_logs_its_partial_text():
    "A task-level cancel skipped the log line, which sat after the `finally`."
    from ramabana.testing import Step
    a = _scripted_agent(Step('partial thought'), Step(tool=('view_file', {'path': '/proj/a.py'})), Step('never reached', pause=.6))
    cells = _logged_turn(a, cancel_at=lambda u: bool(u.acts))
    assert len(cells) == 1 and 'partial thought' in cells[0] and 'never reached' not in cells[0]


def test_the_chunk_in_hand_is_rendered_and_logged_when_cancel_lands():
    "The cancelled check ran before the chunk was drawn, so the last words were dropped."
    from types import SimpleNamespace
    a, _ = fake_agent()
    a.stream_with = lambda ask, image=None: iter(['last words'])
    a.run = lambda run_id='': SimpleNamespace(cancelled=True, terminal=False, state='running')
    (cell,) = _logged_turn(a)
    assert 'last words' in cell
