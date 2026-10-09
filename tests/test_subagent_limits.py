"""Sub-agent limits: steps, a wall clock, opt-in nesting, background runs in `runs`, and pruned run children."""
import threading, time
from fastcore.basics import AttrDict
from ramabana.runtime import Run, CHILD_KEEP
from ramabana.tools import subagent_tools, Slots, SUB_NEST_SP
from ramabana.agent import SUB_DEPTH_MAX
from ramabana.testing import FakeBackend, fake_agent


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


def test_the_step_setting_is_bounded_and_reaches_the_root_tools():
    a, be = fake_agent(subagent_steps=500)
    _stepping(be)
    assert a.subagent_steps == 80
    a.command('/subagents steps 4')
    assert a.subagent_steps == 4 and a.note == 'sub-agent steps 4'
    {t.__name__: t for t in a.tools}['delegate_search'](['q'], max_steps=9)
    assert be.spawned[-1].max_steps == 4


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


def test_a_delegation_inside_its_time_limit_answers_normally():
    out = _subs(FakeBackend(), get_timeout=lambda: 30)['delegate_search'](['q'])
    assert 'time limit' not in out and 'sub answer' in out


def _names(ts): return {t.__name__ for t in ts}


def test_nesting_is_off_by_default_and_gives_only_synchronous_delegation():
    a, _ = fake_agent()
    assert 'delegate_search' not in _names(a._sub_tools())
    a, _ = fake_agent(subagent_depth=1)
    got = _names(a._sub_tools(0))
    assert 'delegate_search' in got
    assert not got & {'delegate_async', 'delegate_result', 'delegate_cancel', 'watch', 'set_plan', 'update_todo'}
    assert 'delegate_search' not in _names(a._sub_tools(1)), 'the last level delegated again'
    assert fake_agent(subagent_depth=9)[0].subagent_depth == SUB_DEPTH_MAX


def test_a_nested_tool_reaches_the_sub_agent_with_one_briefing_line():
    a, be = fake_agent(subagent_depth=1)
    {t.__name__: t for t in a.tools}['delegate_search'](['q'])
    sub = be.spawned[-1]
    assert 'delegate_search' in _names(sub.tools)
    assert SUB_NEST_SP in sub.sp
    a, be = fake_agent()
    {t.__name__: t for t in a.tools}['delegate_search'](['q'])
    assert SUB_NEST_SP not in be.spawned[-1].sp


def test_a_grandchilds_calls_name_the_nested_delegation_as_parent():
    a, be = fake_agent(subagent_depth=1)
    class Sub:
        max_steps = 0
        def __init__(self, tools): self.tools = {t.__name__: t for t in tools}
        def send(self, q, run=None):
            if 'delegate_search' in self.tools: return self.tools['delegate_search'](['deeper'])
            return self.tools['view_file']('/proj/a.py')
        def cancel(self): return True
        def close(self): pass
    be.spawn = lambda sp='', tools=(), **kw: Sub(tools)
    {t.__name__: t for t in a.tools}['delegate_search'](['q'])
    ds, (view,) = [x for x in a.activity.acts if x.tool == 'delegate_search'], [x for x in a.activity.acts if x.tool == 'view_file']
    assert len(ds) == 2 and ds[1].parent_action_id == ds[0].id
    assert view.parent_action_id == ds[1].id, 'the grandchild was filed under the root delegation'


def test_one_tool_budget_covers_the_whole_tree():
    root = Run('r'); child = root.child(); grand = child.child()
    assert [r.draw(3) for r in (child, grand, grand, child)] == [True, True, True, False]


def test_a_sub_agent_waiting_on_its_own_sub_agents_lends_its_slot():
    s, parent, kid = Slots(1), Run('p'), Run('k')
    with s.hold(parent) as ok:
        assert ok
        with s.lend(parent):
            with s.hold(kid) as got: assert got, 'the child waited on a slot its parent held'
        assert parent.slot


def test_a_cancelled_run_stops_waiting_for_a_slot():
    s, a, b = Slots(1), Run('a'), Run('b')
    with s.hold(a):
        b.request_cancel()
        with s.hold(b) as got: assert got is False


def test_settings_refuse_while_busy_and_report_together():
    a, be = fake_agent()
    run = a._new_run('hello'); run.start(be)
    for f in (a.set_subagent_steps, a.set_subagent_timeout, a.set_subagent_depth):
        try: f(2); raise AssertionError('changed while busy')
        except RuntimeError: pass
    assert 'working' in a.command('/subagents on') and a.subagent_writes is False
    run.finish()
    a.tools
    a.command('/subagents nest 2'); a.command('/subagents timeout 0'); a.command('/subagents on')
    assert a._tools is None and a.subagent_depth == 2 and a.subagent_writes
    assert a.command('/subagents').endswith('steps 12 · timeout none · nest 2')
    assert a.command('/subagents nest x').startswith('say /subagents')
    assert a.command('/subagents sideways').startswith('say /subagents')


def test_active_runs_include_live_background_runs_but_not_busy():
    a, be = fake_agent()
    gate = threading.Event()
    rid = a.background.start(lambda r: gate.wait(5), Run('run_bg', 'background', 'q'))
    try:
        assert rid in {r['id'] for r in a.runs(active=True)}
        assert a.busy is False
    finally: gate.set()


def test_finished_children_are_pruned_but_live_ones_kept():
    p = Run('p'); p.start()
    live = p.child('live'); live.start()
    for i in range(CHILD_KEEP + 10): p.child(str(i)).finish()
    assert len(p.children) <= CHILD_KEEP + 1 and live in p.children
    tail = p.child('new'); tail.start()
    assert tail in p.children
    p.detach()
    assert live.state == tail.state == 'detached'
    q = Run('q'); q.start(); k = q.child(); k.start()
    assert q.terminate().state == 'terminated' and k.state == 'terminated'
    w = Run('w'); w.start(); c = w.child(); c.start(); c.finish(); w.finish()
    assert w.wait(0).state == 'completed'
