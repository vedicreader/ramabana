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
    a, be = fake_agent(approvals=agent.Approvals(tools=WRITE_TOOLS, mode='auto'))
    search = next(t for t in a.tools if getattr(t, '__name__', '') == 'delegate_search')

    assert a.subagent_writes is False
    assert {t.__name__ for t in a._sub_plain()} == {t.__name__ for t in a._plain} - agent.ROOT_ONLY
    assert not ({t.__name__ for t in read_only(a.tools)} & WRITE_TOOLS)

    a.command('/subagents on')
    granted = {t.__name__ for t in read_only(a.tools, writes=True, block=NO_SUB)}
    assert 'replace_text' in granted and not (granted & NO_SUB), 'writes yes, recursion never'
    assert a._sub_plain() == [t for t in a.tools if t.__name__ not in agent.ROOT_ONLY]

    before = len(a.calls)
    search(questions=['add a docstring to a.py'])
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
