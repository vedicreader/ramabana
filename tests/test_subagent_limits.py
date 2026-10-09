"""Sub-agent limits: steps, a wall clock, opt-in nesting, background runs in `runs`, and pruned run children."""
import threading, time
from fastcore.basics import AttrDict
from ramabana.runtime import Run
from ramabana.tools import subagent_tools, Slots
from ramabana.testing import FakeBackend


def view_file(path: str) -> str:
    "A read tool."
    return 'x=1'


def _subs(be, **kw): return {t.__name__: t for t in subagent_tools(lambda: be, lambda: [view_file], **kw)}


def _stepping(be):
    "Give `be`'s sub-agents the `max_steps` a rishi chat has."
    spawn = be.spawn
    be.spawn = lambda **kw: setattr(s := spawn(**kw), 'max_steps', 0) or s
    return be


def test_a_delegations_max_steps_is_capped_by_the_session_and_floored():
    """A turn model asked for five or eight steps, and its sub-agents ran out before they could report.
    A delegation gets at least `SUB_MAX_STEPS`, within the session's cap, and is told the budget notice is ours."""
    from ramabana.tools import SUB_MAX_STEPS, sub_briefing
    be = _stepping(FakeBackend())
    subs = _subs(be, get_steps=lambda: 20)
    for n in (50, 3, 0): subs['delegate_search'](['q'], max_steps=n)
    _subs(be, get_steps=lambda: 5)['delegate_search'](['q'], max_steps=3)
    assert [s.max_steps for s in be.spawned] == [20, SUB_MAX_STEPS, 20, 5]
    assert 'budget' in sub_briefing() and 'harness' in sub_briefing()


class _Hung:
    "A sub-agent that never answers until it is cancelled."
    max_steps = 0
    def __init__(self): self.release = threading.Event()
    def send(self, q, run=None): self.release.wait(10); return 'late'
    def cancel(self): self.release.set(); return True
    def close(self): pass


def test_each_hung_worker_is_stopped_by_its_own_time_limit():
    be = AttrDict(spec=AttrDict(name='fake', local=False), spawn=lambda **kw: _Hung())
    subs = _subs(be, get_timeout=lambda: .2)
    t0 = time.monotonic()
    out = subs['delegate_search'](['a', 'b', 'c'])
    assert time.monotonic() - t0 < 5
    assert out.count('time limit') == 3, out


def test_a_sub_agent_waiting_on_its_own_sub_agents_lends_its_slot():
    s, parent, kid = Slots(1), Run('p'), Run('k')
    with s.hold(parent) as ok:
        assert ok
        with s.lend(parent):
            with s.hold(kid) as got: assert got, 'the child waited on a slot its parent held'
        assert parent.slot
