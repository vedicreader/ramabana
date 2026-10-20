"""The approval gate: which calls are put to a person, and what comes back when they say no.

The point of the whole module is the reason, not the refusal. "Denied" teaches a model nothing and
gets retried; "that file is generated, edit the notebook instead" changes its approach. So every
test here is really about whether the reason survives the trip back.
"""
import threading
import time

from ramabana import agent
from ramabana.testing import fake_agent
from ramabana.tools import WRITE_TOOLS


def edit_call(path='a.py'): return {'function': {'name': 'edit_file', 'arguments': {'path': path}}}


def answer_when_asked(ap, ok, note=''):
    "Answer the next pending ask from another thread, the way a frontend does."
    def run():
        for _ in range(10):
            if (a := ap.pending) is not None: return ap.answer(a.id, ok, note)
            time.sleep(0.01)
    threading.Thread(target=run, daemon=True).start()


def test_a_writing_sub_agent_is_recorded_and_gated_the_way_the_main_agent_is():
    """`Backend.spawn` inherits no `approve`, and `_sub_plain` handed over the unwrapped tools, so a
    sub-agent granted writes would edit with no prompt and leave nothing in `calls`. Both are the
    toggle's to close.
    """
    from ramabana.tools import NO_SUB, SUB_READ_SP, SUB_WRITE_SP, read_only, sub_briefing
    a, be = fake_agent(approvals=agent.Approvals(tools=WRITE_TOOLS, mode='auto'), subagent_depth=0)
    search = next(t for t in a.tools if getattr(t, '__name__', '') == 'delegate_search')

    assert a.subagent_writes is True
    assert {t.__name__ for t in a._sub_plain()} == {t.__name__ for t in a.tools} - agent.ROOT_ONLY
    assert not ({t.__name__ for t in read_only(a.tools)} & WRITE_TOOLS)

    a.command('/subagents on')
    granted = {t.__name__ for t in read_only(a.tools, writes=True, block=NO_SUB)}
    assert 'replace_text' in granted and not (granted & NO_SUB), 'writes yes, recursion never'
    assert a._sub_plain() == [t for t in a.tools if t.__name__ not in agent.ROOT_ONLY]

    before = len(a.calls)
    search(questions=['add a docstring to a.py'], writes=True)
    spawned = be.spawned[-1]
    assert spawned.approve is not None and len(a.calls) > before
    # the briefing is built from named halves, so these are the halves and not a phrase to match
    assert SUB_READ_SP not in spawned.sp, 'a writing sub-agent was still told it cannot edit'
    assert SUB_WRITE_SP in spawned.sp

    a.command('/subagents off')
    assert a.subagent_writes is False and a._sub_plain() == [t for t in a._plain if t.__name__ not in agent.ROOT_ONLY]
    search(questions=['where else do we do X?'])
    assert be.spawned[-1].approve is None
    assert SUB_READ_SP in be.spawned[-1].sp
    assert SUB_WRITE_SP not in be.spawned[-1].sp
    assert sub_briefing() != sub_briefing(writes=True)


def test_a_refusal_always_carries_a_reason_the_model_can_act_on():
    "And an approval carries one too, when the person had something to add to it."
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    answer_when_asked(ap, False, 'that file is generated, edit the notebook instead')
    d = ap.gate(edit_call('gen.py'))
    stop()
    assert not d and 'that file is generated' in d.reply()

    off = agent.Approvals(tools={'edit_file'}, mode='off')
    d2 = off.gate(edit_call())
    assert not d2 and agent.DENIED in d2.reply() and 'switched off' in d2.reply()

    auto = agent.Approvals(tools={'edit_file'}, mode='auto')
    assert auto.request('edit_file', {'path': 'a.py'}).reply() is None   # nothing to say
    assert agent.Ask(tool='edit_file').resolve(True, 'keep the docstring').reply(
        ).endswith('keep the docstring')


def test_a_refusal_nobody_could_be_asked_about_still_reaches_the_recorder():
    """Otherwise it surfaces as a bare tool failure with the explanation nowhere in the UI. And a
    blocked worker thread is a hung IDE, so refusing fast is a bad answer that is at least an
    answer -- as is a cancelled turn releasing whatever was waiting on it."""
    heard = []
    agent.Approvals(tools={'edit_file'}, mode='off', on_answer=heard.append).gate(edit_call())
    agent.Approvals(tools={'edit_file'}, on_answer=heard.append).gate(edit_call())  # none listening
    assert len(heard) == 2 and all(not a and a.note for a in heard)

    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate(edit_call())
    assert not d and time.time() - t0 < 1 and 'nothing is listening' in d.reply()

    live = agent.Approvals(tools={'edit_file'}, timeout=30)
    stop = live.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), live.cancel_all()), daemon=True).start()
    c = live.gate(edit_call())
    stop()
    assert not c and 'cancelled' in c.reply()


def test_every_tool_named_a_write_is_also_marked_one():
    """The two representations are kept in two packages: shalya marks the tool, Ramabana adds the
    names shalya has never heard of. Nothing failed when they disagreed."""
    from shalya.core import is_write
    from ramabana.testing import FullHost, fake_agent
    from ramabana.shop import Cart, cart_tools
    from ramabana.tools import WRITE_TOOLS, tools_for

    built = list(tools_for(FullHost())) + list(cart_tools(Cart()))
    a, _ = fake_agent()
    built += [t for t in a.tools if t.__name__ not in {x.__name__ for x in built}]
    by = {t.__name__: t for t in built}
    named_not_marked = sorted(n for n in WRITE_TOOLS if n in by and not is_write(by[n]))
    marked_not_named = sorted(n for n, t in by.items() if is_write(t) and n not in WRITE_TOOLS)
    assert named_not_marked == [], f'in WRITE_TOOLS and not marked: {named_not_marked}'
    assert marked_not_named == [], f'marked and not in WRITE_TOOLS: {marked_not_named}'


def test_the_same_gated_call_three_times_running_is_put_to_the_person_whatever_the_mode():
    """A model that repeats one gated call, args and all, is looping: `auto` would let it spin and
    `ask` would nag with the same question. The third repeat is an explicit ask through the ordinary
    request path (so a CLI waits, and a frontend re-asks), and where nobody can be asked it is
    refused with the loop named, on the recorder like any other refusal."""
    heard, asked = [], []
    ap = agent.Approvals(tools={'edit_file'}, mode='auto', timeout=5, on_answer=heard.append)
    stop = ap.listen(on_ask=lambda a: (asked.append(a), ap.answer(a.id, False, 'stop looping')))
    call = edit_call('a.py')
    assert ap.gate(call) and ap.gate(call) and not asked           # auto: the first two run unasked
    d = ap.gate(call)
    assert not d and 'stop looping' in d.reply() and 'three times' in asked[0].preview
    assert ap.gate(edit_call('b.py')) and len(asked) == 1           # a different call is not the loop
    assert ap.gate(call) and ap.gate(call) and ap.gate(call).answer is False   # and it counts afresh
    stop()

    lone = agent.Approvals(tools={'edit_file'}, mode='auto', on_answer=heard.append)
    assert lone.gate(call) and lone.gate(call)
    d = lone.gate(call)
    assert not d and 'three times' in d.reply() and 'listening' in d.reply()
    assert heard[-1] is d, 'the recorder hears the refusal'

    ap = agent.Approvals(tools={'edit_file'}, mode='off')
    assert all(ap.gate(call).answer is False for _ in range(3))    # `off` refuses before any of this
    assert all(agent.Approvals(tools={'edit_file'}).gate({'function': {'name': 'search_code', 'arguments': {'q': 'x'}}}) for _ in range(4))   # an ungated call is never the loop


def _until(cond, secs=3):
    for _ in range(int(secs / .01)):
        if cond(): return True
        time.sleep(.01)
    return False

def _ask_in_thread(ap, path, out, run=None):
    "Raise one edit ask from its own thread, inside `run` when one is given, as a sub-agent would."
    from ramabana.runtime import run_context
    def go():
        if run is None: out[path] = ap.request('edit_file', {'path': path})
        else:
            with run_context(run): out[path] = ap.request('edit_file', {'path': path})
    t = threading.Thread(target=go, daemon=True); t.start()
    return t


def test_asks_raised_together_are_each_answered_by_id_and_each_reported():
    "A sub-agent and the turn asking at once: the older ask stayed unanswerable once the newer replaced it."
    answered, out = [], {}
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    ap.listen(on_ask=lambda a: None, on_answer=answered.append)
    ts = [_ask_in_thread(ap, 'a.py', out)]
    assert _until(lambda: len(ap.waiting) == 1)
    ts.append(_ask_in_thread(ap, 'b.py', out))
    assert _until(lambda: len(ap.waiting) == 2)
    first, second = ap.waiting
    assert ap.pending is first and ap.current is second, 'pending is the oldest, current the newest'
    assert ap.answer(second.id, False, 'not b') is not None and ap.answer(first.id, True) is not None
    for t in ts: t.join(2)
    assert bool(out['a.py']) and not out['b.py'] and out['b.py'].note == 'not b'
    assert {a.id for a in answered} == {first.id, second.id} and ap.waiting == []
    assert ap.answer(first.id, True) is None, 'an ask is answered once'
    ts = [_ask_in_thread(ap, p, out) for p in ('c.py', 'd.py')]
    assert _until(lambda: len(ap.waiting) == 2)
    ap.close()
    for t in ts: t.join(2)
    assert not out['c.py'] and not out['d.py'] and 'closed' in out['d.py'].note


def test_cancelling_a_run_refuses_its_asks_and_leaves_another_runs():
    from ramabana.runtime import Run
    out = {}
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    ap.listen(on_ask=lambda a: None)
    root, other = Run('root'), Run('other', kind='delegate')
    child = Run('child', kind='delegate', parent=root)
    ts = [_ask_in_thread(ap, 'mine.py', out, run=child), _ask_in_thread(ap, 'theirs.py', out, run=other)]
    assert _until(lambda: len(ap.waiting) == 2)
    ap.cancel_all('the run was cancelled', run=root)
    ts[0].join(2)
    assert not out['mine.py'] and [a.args['path'] for a in ap.waiting] == ['theirs.py'], 'a child of the cancelled run'
    ap.cancel_all()
    ts[1].join(2)
    assert not out['theirs.py'] and ap.waiting == []


def test_an_ask_can_wait_for_a_page_and_a_timeout_can_allow():
    "A host whose page restarts waits for it to reconnect; the page that joins late is shown what is waiting."
    out = {}
    ap = agent.Approvals(tools={'edit_file'}, timeout=5, no_listener='wait')
    t = _ask_in_thread(ap, 'a.py', out)
    assert _until(lambda: len(ap.waiting) == 1) and 'a.py' not in out
    shown = []
    ap.listen(on_ask=shown.append)
    assert [a.args['path'] for a in shown] == ['a.py']
    ap.answer(shown[0].id, True); t.join(2)
    assert bool(out['a.py'])
    refusing = agent.Approvals(tools={'edit_file'}, timeout=5)
    assert not refusing.request('edit_file', {'path': 'b.py'}), 'refuse when nothing listens is still the default'
    quiet = agent.Approvals(tools={'edit_file'}, timeout=.05, on_timeout='allow')
    quiet.listen(on_ask=lambda a: None)
    late = quiet.request('edit_file', {'path': 'c.py'})
    assert bool(late) and 'no answer' in late.note
    strict = agent.Approvals(tools={'edit_file'}, timeout=.05)
    strict.listen(on_ask=lambda a: None)
    assert not strict.request('edit_file', {'path': 'd.py'})


def test_mk_agent_passes_the_wait_policies_to_its_approvals(tmp_path):
    a, _ = agent.mk_agent([str(tmp_path)], cfg=tmp_path, timeout=30, no_listener='wait', on_timeout='allow', extensions=False, subagents=False)
    ap = a.approvals
    assert (ap.timeout, ap.no_listener, ap.on_timeout) == (30, 'wait', 'allow')
    a.close()


def _reads_only(name, args):
    "A host's rule: `run_shell` runs `rg`, `ls` and `cat` unasked, and anything else is put to a person."
    if name != 'run_shell': return None
    return 'allow' if str(args.get('command', '')).split()[:1] in (['rg'], ['ls'], ['cat']) else 'ask'

def test_a_host_policy_comes_before_rules_and_modes_and_the_loop_guard_still_asks():
    asked = []
    ap = agent.Approvals(tools={'run_shell'}, mode='auto', timeout=.05, policy=_reads_only)
    ap.listen(on_ask=asked.append)
    assert ap.request('run_shell', {'command': 'rg foo'})
    assert not ap.request('run_shell', {'command': 'rm -rf build'}) and asked[-1].args['command'] == 'rm -rf build', 'asked even in auto'
    n = len(asked)
    assert ap.request('run_shell', {'command': 'ls'}) and ap.request('run_shell', {'command': 'ls'})
    assert not ap.request('run_shell', {'command': 'ls'}) and len(asked) == n + 1, 'the third identical call still asks'
    broken = agent.Approvals(tools={'run_shell'}, mode='auto', timeout=.05, policy=lambda name, args: 1 / 0)
    broken.listen(on_ask=lambda a: None)
    assert not broken.request('run_shell', {'command': 'ls'}), 'a policy that fails asks, it never allows'
    strict = agent.Approvals(policy=lambda name, args: 'deny' if name == 'view_file' else None)
    assert not strict.request('view_file', {'path': 'x'}) and strict.request('grep', {'pattern': 'x'})


def test_an_extension_approval_policy_reaches_the_gate():
    "`registry.approval(fn)` was stored and never read."
    a, _ = fake_agent(approvals=agent.Approvals(tools={'run_shell'}, mode='auto'))
    a.registry.approval(lambda name, args: 'deny' if name == 'run_shell' else None)
    assert not a.approvals.request('run_shell', {'command': 'ls'})
    assert a.approvals.request('view_file', {'path': 'x'})


def test_an_ask_waiting_for_a_person_shows_in_the_activity_before_its_call_runs():
    "No act existed until a call was approved, so a host could not show it was waiting; the spike lost 11 minutes to one."
    seen, out = [], {}
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    a, _ = fake_agent(approvals=ap, on_activity=seen.append)
    ap.listen(on_ask=lambda x: None)
    t = _ask_in_thread(ap, 'a.py', out)
    assert _until(lambda: any(x.state == 'awaiting' for x in seen))
    act = next(x for x in seen if x.state == 'awaiting')
    assert act.kind == 'ask' and act.ask_id == ap.pending.id and 'a.py' in act.summary and act.in_prompt
    ap.answer(act.ask_id, True); t.join(2)
    assert act.done and act.ok and act.in_prompt, 'an approved ask stays with the prompt that asked it'
    t = _ask_in_thread(ap, 'b.py', out)
    assert _until(lambda: len(ap.waiting) == 1)
    ap.answer(ap.pending.id, False, 'not that file'); t.join(2)
    refused = [x for x in seen if x.kind == 'ask' and 'b.py' in x.summary][-1]
    assert refused.done and not refused.ok and not refused.in_prompt and 'not that file' in refused.detail
    ap.mode = 'auto'
    before = len([x for x in seen if x.state == 'awaiting'])
    assert ap.request('edit_file', {'path': 'c.py'})
    assert len([x for x in seen if x.state == 'awaiting']) == before, 'an ask the mode decides waits for nobody'


def test_a_page_joining_while_an_ask_is_raised_hears_of_it_once_and_a_policy_ask_waits_for_a_person():
    seen = []
    ap = agent.Approvals(tools={'run_shell'}, timeout=.2, on_timeout='allow', policy=_reads_only)
    a = ap.ask('run_shell', {'command': 'rm -rf build'})
    w = (seen.append, None)
    ap._watchers.append(w); ap._asks[a.id] = a   # the page registered, and the ask was stored, before either was told
    ap._show(w, a); ap._notify('ask', a)
    assert seen == [a], 'replay and notify together tell a page once'
    ap._asks.clear(); ap._watchers.clear()
    ap.listen(on_ask=lambda x: None)
    out = ap.request('run_shell', {'command': 'rm -rf build'})
    assert out.forced == 'policy' and not out, 'a timeout never allows what the policy put to a person'
    ap2 = agent.Approvals(tools={'run_shell'}, timeout=5, policy=_reads_only)
    ap2.listen(on_ask=lambda x: None)
    out2 = {}
    t = threading.Thread(target=lambda: out2.setdefault('r', ap2.request('run_shell', {'command': 'rm x'})), daemon=True); t.start()
    assert _until(lambda: len(ap2.waiting) == 1)
    ap2.set_mode('auto')
    assert len(ap2.waiting) == 1, '/approve auto leaves what the policy put to a person'
    ap2.close(); t.join(2)
    assert not out2['r']
