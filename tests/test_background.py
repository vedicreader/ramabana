"""Delegations that outlive the turn that started them, and the gate they answer to.

The notebook shows one of each working. What is worth a plain test is the handshake: a handle
that names an unregistered run, a worker that keeps going after a cancel, an approval nobody is
there to answer. Those are the failures a background delegation has and a foreground one does not.
"""
import threading
import time

from ramabana.agent import Agent, Approvals, Ask
from ramabana.runtime import Run
from ramabana.testing import FakeBackend, MemHost
from ramabana.tools import WRITE_TOOLS, Background, subagent_tools


def until(f, secs=5):
    "Wait for `f()` to be truthy, and return whether it became so."
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if f(): return True
        time.sleep(.01)
    return bool(f())


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


# -- approvals for work nobody is watching -----------------------------------------------

def test_a_background_run_does_not_keep_the_session_busy():
    """A turn whose child is still live never goes idle, and `busy` blocks `/resume`, `/model` and
    the sub-agent write toggle. A background delegation is parentless for exactly this reason."""
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False, profile='full')
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
