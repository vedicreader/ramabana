"""Delegations that outlive the turn that started them, and the gate they answer to.

The notebook shows one of each working. What is worth a plain test is the handshake: a handle
that names an unregistered run, a worker that keeps going after a cancel, an approval nobody is
there to answer. Those are the failures a background delegation has and a foreground one does not.
"""
import threading
import time

import pytest

from ramabana.agent import Agent, Approvals, Ask
from ramabana.runtime import Run, run_context
from ramabana.testing import FakeBackend, MemHost
from ramabana.tools import ERR, WRITE_TOOLS, Background, NO_SUB, subagent_tools


def until(f, secs=5):
    "Wait for `f()` to be truthy, and return whether it became so."
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if f(): return True
        time.sleep(.01)
    return bool(f())


def test_a_handle_is_only_returned_once_the_run_it_names_is_registered():
    bg, seen = Background(), []
    ids = [bg.start(lambda r: 'done', Run(f'run_{i}', 'child', 'q')) for i in range(20)]
    # every id resolves the moment it is handed back, which is the whole point of a handle
    for rid in ids: assert bg.status(rid)[0]['id'] == rid
    assert {r['id'] for r in bg.status()} == set(ids)


def test_work_past_the_ceiling_waits_rather_than_running():
    bg, gate, ran = Background(mx=2), threading.Event(), []

    def hold(run):
        run.start()
        ran.append(run.id)
        gate.wait(5)
        return 'done'

    for i in range(5): bg.start(hold, Run(f'run_{i}', 'child', 'q'))
    assert until(lambda: len(ran) == 2)
    time.sleep(.1)
    assert len(ran) == 2, 'the ceiling let more than two reach the callback'
    states = {r['id']: r['state'] for r in bg.status()}
    assert sum(s == 'running' for s in states.values()) == 2
    assert sum(s == 'pending' for s in states.values()) == 3
    gate.set()
    assert until(lambda: len(ran) == 5)


def test_a_run_cancelled_while_it_waits_emits_nothing_and_says_it_stopped():
    bg, gate, ran = Background(mx=1), threading.Event(), []

    def hold(run):
        run.start()
        ran.append(run.id)
        gate.wait(5)
        return 'done'

    bg.start(hold, Run('run_holds', 'child', 'q'))
    bg.start(hold, Run('run_waits', 'child', 'q'))
    assert until(lambda: ran == ['run_holds'])
    assert bg.cancel('run_waits') == 'run_waits is stopping'
    gate.set()
    assert until(lambda: 'stopped' in bg.result('run_waits'))
    assert ran == ['run_holds'], 'a cancelled run reached its callback anyway'
    assert 'stopped (cancelled)' in bg.result('run_waits')


def test_closing_refuses_new_work_and_stops_what_was_queued():
    bg, gate, ran = Background(mx=1), threading.Event(), []
    bg.start(lambda r: (r.start(), gate.wait(5), ran.append(r.id))[2], Run('run_1', 'child', 'q'))
    bg.start(lambda r: ran.append(r.id), Run('run_2', 'child', 'q'))
    assert until(lambda: bg.status('run_1')[0]['state'] == 'running')

    assert bg.close() == 2
    with pytest.raises(Exception, match='closing'):
        bg.start(lambda r: 'nope', Run('run_3', 'child', 'q'))
    gate.set()
    assert until(lambda: 'stopped' in bg.result('run_2'))
    assert 'run_2' not in ran, 'a queued run reached a model after the session closed'


def test_a_callback_that_raises_is_the_runs_answer_rather_than_a_lost_run():
    bg = Background()
    bg.start(lambda r: 1 / 0, Run('run_boom', 'child', 'q'))
    assert until(lambda: ERR in bg.result('run_boom'))
    assert 'ZeroDivisionError' in bg.result('run_boom')
    assert bg.status('run_boom')[0]['state'] in ('completed', 'failed')


def test_an_answer_that_aged_out_says_so_rather_than_looking_unfinished():
    bg = Background(keep=1)
    for n in ('run_a', 'run_b'): bg.start(lambda r: f'ans {r.id}', Run(n, 'child', 'q'))
    assert until(lambda: bg.result('run_b') == 'ans run_b')
    assert 'no longer held' in bg.result('run_a')


def test_every_reader_of_an_unknown_run_says_so_rather_than_raising():
    bg = Background()
    for f in (bg.status, bg.result, bg.cancel):
        assert str(f('run_nope')).startswith('no delegation named')


# -- the tools over it -------------------------------------------------------------------

def edit_file(path: str, commands: str) -> str:
    "A write tool, so a test can see whether one was handed over."
    return 'edited'


def view_file(path: str) -> str:
    "A read tool, which every sub-agent gets."
    return 'x=1'


TOOLS = [edit_file, view_file]


def _subs(be, writes=False, approve=None, bg=None, tools=TOOLS):
    return {t.__name__: t for t in subagent_tools(
        lambda: be, lambda: list(tools), get_writes=lambda: writes,
        get_approve=(lambda: approve) if approve else None, background=bg)}


def test_the_async_tools_are_withheld_from_a_sub_agent():
    for n in ('delegate_async', 'delegate_status', 'delegate_result', 'delegate_cancel'):
        assert n in NO_SUB, f'{n} lets a sub-agent collect work it did not start'


def test_a_background_delegation_is_read_only_even_where_the_session_grants_writes():
    be = FakeBackend()
    subs = _subs(be, writes=True, approve=lambda tc: True)
    assert 'read-only' in subs['delegate_async']('look at this')
    assert until(lambda: be.spawned)
    got = {t.__name__ for t in be.spawned[0].tools or ()}
    assert 'edit_file' in WRITE_TOOLS, 'the fixture stopped naming a real write tool'
    assert be.spawned[0].approve is None, 'a read-only run was handed a gate it has no use for'
    # the session says sub-agents may write; a run nobody is watching still does not get them
    assert got & WRITE_TOOLS == set(), got
    assert 'view_file' in got, 'the read tools went missing too, so the check proved nothing'


def test_writes_are_granted_only_when_the_call_asks_and_the_session_allows():
    off = _subs(FakeBackend(), writes=False)
    assert 'read-only' in off['delegate_async']('q', writes=True), 'the session setting is the ceiling'
    be = FakeBackend()
    on = _subs(be, writes=True, approve=lambda tc: True)
    assert 'with write tools' in on['delegate_async']('q', writes=True)
    assert until(lambda: be.spawned)
    assert 'edit_file' in {t.__name__ for t in be.spawned[0].tools or ()}
    # and the gate travels with them: writes with nothing to answer to is the failure this guards
    assert be.spawned[0].approve is not None


def test_a_delegation_with_no_model_says_so_rather_than_starting_a_run():
    bg = Background()
    subs = _subs(None, bg=bg)
    assert subs['delegate_async']('q') == 'no model is available to delegate to'
    assert bg.status() == [], 'a run was registered for work that never started'


# -- approvals for work nobody is watching -----------------------------------------------

def test_an_ask_carries_the_run_that_raised_it():
    a = Approvals(tools={'edit_file'}, mode='auto')
    with run_context(Run('run_bg', 'child', 'q')):
        got = a.request('edit_file', {'path': '/p/x.py'})
    assert got.run_id == 'run_bg'
    assert got.dict()['run_id'] == 'run_bg'
    assert a.request('edit_file', {}).run_id == '', 'a foreground ask claims no run'


def test_an_ask_with_nobody_listening_is_refused_at_once_rather_than_timing_out():
    a = Approvals(tools={'edit_file'}, mode='ask', timeout=30)
    start = time.monotonic()
    got = a.request('edit_file', {'path': '/p/x.py'})
    assert time.monotonic() - start < 1, 'it waited out the timeout instead of refusing'
    assert got.answer is False and 'nothing is listening' in got.note


def test_a_closing_session_refuses_what_was_waiting_and_everything_after():
    a = Approvals(tools={'edit_file'}, mode='ask', timeout=30)
    a.listen(on_ask=lambda ask: None)
    answered = []
    done = threading.Event()

    def asker():
        answered.append(a.request('edit_file', {'path': '/p/x.py'}))
        done.set()

    threading.Thread(target=asker, daemon=True).start()
    assert until(lambda: a.pending is not None)
    a.close()
    assert done.wait(5), 'closing left the model thread blocked on an approval'
    assert answered[0].answer is False and 'closed' in answered[0].note
    # and the gate stays shut for anything raised after
    assert a.request('edit_file', {}).answer is False


def test_closing_an_agent_stops_its_background_work_and_shuts_the_gate():
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False,
              approvals=Approvals(tools=WRITE_TOOLS, mode='ask'))
    a._backends[('fake', 'fake')] = FakeBackend()
    a.background.start(lambda r: 'done', Run('run_live', 'child', 'q'))
    a.close()
    assert a.background.open is False
    assert a.approvals.closed is True


def test_a_background_run_does_not_keep_the_session_busy():
    """A turn whose child is still live never goes idle, and `busy` blocks `/resume`, `/model` and
    the sub-agent write toggle. A background delegation is parentless for exactly this reason."""
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    be = FakeBackend()
    a._backends[('fake', 'fake')] = be
    gate = threading.Event()
    be.spawn = lambda sp='', tools=(), **kw: type('S', (), {
        'send': lambda s, q, run=None: (gate.wait(5), 'x')[1], 'close': lambda s: None,
        'max_steps': 0, 'tools': [], 'cancelled': False})()
    subs = {t.__name__: t for t in a.tools if t.__name__.startswith('delegate')}
    try:
        rid = subs['delegate_async']('a long job').split()[1]
        assert until(lambda: a.background.status(rid)[0]['state'] == 'running')
        assert a.busy is False, 'a background delegation held the session open'
        a.set_model('claude/claude-sonnet-4-5')      # would raise while busy
    finally:
        gate.set()
        a.close()


def test_a_finished_run_is_never_reported_as_having_lost_its_answer():
    """`result` said "no longer held" for any terminal run with no answer stored, which included the
    window between `run.finish()` and the answer being written, and a run cancelled while queued."""
    bg, gate, = Background(mx=1), threading.Event()
    bg.start(lambda r: (r.start(), gate.wait(5), 'first')[2], Run('run_holds', 'child', 'q'))
    bg.start(lambda r: 'second', Run('run_queued', 'child', 'q'))
    assert until(lambda: bg.status('run_holds')[0]['state'] == 'running')

    bg.cancel('run_queued')
    assert bg.status('run_queued')[0]['state'] in ('cancelled', 'cancelling')
    # terminal, and its worker has not written anything yet. It has not lost an answer; it has none
    assert 'no longer held' not in bg.result('run_queued'), bg.result('run_queued')
    gate.set()
    assert until(lambda: 'stopped' in bg.result('run_queued'))


def test_every_pending_ask_is_refused_when_the_session_closes_not_only_the_newest():
    a = Approvals(tools={'edit_file'}, mode='ask', timeout=30)
    a.listen(on_ask=lambda ask: None)
    got, done = [], threading.Event()

    def asker(path):
        got.append(a.request('edit_file', {'path': path}))
        if len(got) == 2: done.set()

    for p in ('/p/one.py', '/p/two.py'):
        threading.Thread(target=asker, args=(p,), daemon=True).start()
        time.sleep(.05)
    assert until(lambda: sum(x.pending for x in a.history) == 2)
    assert len(a.close()) == 2, 'only the newest ask was refused'
    assert done.wait(5), 'a thread was left blocked on an approval nobody could answer'
    assert all(x.answer is False for x in got)


def test_an_ask_arriving_as_the_session_closes_is_refused_rather_than_left_waiting():
    """`request` checked `closed` and then stored `current` separately. An ask landing in that gap
    waited out its whole timeout with nobody able to answer it."""
    a = Approvals(tools={'edit_file'}, mode='ask', timeout=2)
    a.listen(on_ask=lambda ask: None)
    a.close()
    start = time.monotonic()
    got = a.request('edit_file', {'path': '/p/x.py'})
    assert time.monotonic() - start < 1
    assert got.answer is False and 'closing' in got.note
