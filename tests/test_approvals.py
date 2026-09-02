"""The approval gate: which calls are put to a person, and what comes back when they say no.

The point of the whole module is the reason, not the refusal. "Denied" teaches a model nothing and
gets retried; "that file is generated, edit the notebook instead" changes its approach. So every
test here is really about whether the reason survives the trip back.
"""
import inspect
import threading
import time

import pytest

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


def test_the_gate_draws_its_line_around_the_write_tools_and_answers_as_a_bool():
    """Both engines call `approve(tc)` and branch on the result, so it has to be falsy when
    refused. The line is not only the filesystem: deleting a standing reminder and spending money
    in a trolley are both things a person should see before they happen. `add_root` is the widest of
    them: it moves the boundary the rest are checked against. And a sub-agent nobody is watching gets
    none of them -- a delegated question is a question.
    """
    from ramabana.tools import GIT_READ_TOOLS, GIT_WRITE_TOOLS
    assert {'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
            'run_shell', 'memory_forget', 'create_skill', 'cancel_watch', 'cart_add',
            'cart_remove', 'add_root'} | GIT_WRITE_TOOLS == set(WRITE_TOOLS)
    assert not (set(GIT_READ_TOOLS) & set(WRITE_TOOLS)), 'rehearsing a merge is not approving one'

    ap = agent.Approvals(tools={'edit_file'}, mode='auto')
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})   # ungated
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': '{"path": "a.py"}'}})
    assert bool(d) and d.args == {'path': 'a.py'}                 # arguments parsed either shape

    from ramabana.tools import read_only
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS) and 'search_code' in names


def test_a_writing_sub_agent_is_recorded_and_gated_the_way_the_main_agent_is():
    """`Backend.spawn` inherits no `approve`, and `_sub_plain` handed over the unwrapped tools, so a
    sub-agent granted writes would edit with no prompt and leave nothing in `calls`. Both are the
    toggle's to close.
    """
    from ramabana.tools import NO_SUB, SUB_READ_SP, SUB_WRITE_SP, read_only, sub_briefing
    a, be = fake_agent(approvals=agent.Approvals(tools=WRITE_TOOLS, mode='auto'))
    search = next(t for t in a.tools if getattr(t, '__name__', '') == 'delegate_search')

    assert a.subagent_writes is False
    assert {t.__name__ for t in a._sub_plain()} == {t.__name__ for t in a._plain}
    assert not ({t.__name__ for t in read_only(a.tools)} & WRITE_TOOLS)

    a.command('/subagents on')
    granted = {t.__name__ for t in read_only(a.tools, writes=True, block=NO_SUB)}
    assert 'edit_file' in granted and not (granted & NO_SUB), 'writes yes, recursion never'
    assert a._sub_plain() is a.tools

    before = len(a.calls)
    search(question='add a docstring to a.py')
    spawned = be.spawned[-1]
    assert spawned.approve is not None and len(a.calls) > before
    # the briefing is built from named halves, so these are the halves and not a phrase to match
    assert SUB_READ_SP not in spawned.sp, 'a writing sub-agent was still told it cannot edit'
    assert SUB_WRITE_SP in spawned.sp

    a.command('/subagents off')
    assert a.subagent_writes is False and a._sub_plain() is a._plain
    search(question='where else do we do X?')
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


def test_every_watcher_and_the_recorder_hear_the_same_ask_with_a_preview():
    """A second frontend opening must not unhook the notebook recorder, or the first frontend. The
    preview is what makes an approval answerable: a hash address and a diff, not a tool name."""
    seen = []
    ap = agent.Approvals(tools={'edit_file'}, mode='auto', on_ask=lambda a: seen.append('recorder'))
    ap.listen(on_ask=lambda a: seen.append('one'))
    ap.listen(on_ask=lambda a: seen.append('two'))
    ap.mode = 'ask'
    answer_when_asked(ap, True)
    ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert sorted(seen) == ['one', 'recorder', 'two']

    p = agent.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = agent.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2

    # Hosted approvals reach rishi's own remote path now, so the shim is three functions saying so.
    assert agent.apply() and agent.apply() and agent.applied()


def test_a_readonly_agent_is_not_given_the_tools_that_act():
    """`read_only` existed but only the sub-agent path reached it, and the nearest thing an agent
    had was a briefing that asked it not to write while `edit_file` stayed on the list. A surface
    that only proposes needs the tools gone, not discouraged."""
    from ramabana.tools import ACTING_TOOLS, NO_SUB, read_only

    open_agent, _ = fake_agent()
    shut, _ = fake_agent(readonly=True)
    names = {t.__name__ for t in shut.tools}

    assert not (names & WRITE_TOOLS), f'a write survived: {sorted(names & WRITE_TOOLS)}'
    assert not (names & ACTING_TOOLS), f'an effect survived: {sorted(names & ACTING_TOOLS)}'
    assert not (names & NO_SUB), 'a read-only agent does not delegate its way around the refusal'
    assert 'search_code' in names, 'it can still look, or it is no use'
    # `_plain` is what the briefing is written from: it has to agree with what was built, or the
    # model is told about a tool it has not got.
    assert {t.__name__ for t in shut._plain} == names
    assert WRITE_TOOLS & {t.__name__ for t in open_agent.tools}, 'the default is unchanged'


def test_a_readonly_agent_can_be_held_to_a_number_of_calls():
    "The budget guard `read_only` already had, reachable now without delegating."
    a, _ = fake_agent(readonly=True, readonly_calls=1)
    look = next(t for t in a.tools if t.__name__ == 'search_code')
    look(query='a')
    spent = str(look(query='a'))
    assert 'budget exhausted' in spent.lower()
    assert 'sub-agent' not in spent.lower(), 'the guard is no longer only a sub-agent one'


def test_a_readonly_agent_cannot_leave_a_page_it_read_in_the_vault():
    "`read_url` is a read, but its `remember=True` default writes; the argument is not the model's."
    from ramabana.testing import MemHost
    from ramabana.tools import WebHost, read_only, tools_for

    seen = []
    class Page: text = 'page'
    # the web group is declared by inheriting `WebHost`, and declaring it means writing all three
    class Host(MemHost, WebHost):
        def web_search(self, query, n=20): return []
        def research(self, query): return ''
        def read_url(self, url, remember=True):
            seen.append(remember)
            return Page()

    ts = tools_for(Host({'/p/a.py': 'x=1'}))
    fetch = next(t for t in read_only(ts) if t.__name__ == 'read_url')
    fetch(url='https://example.com')
    assert seen == [False], f'the vault write survived: {seen}'
    # shalya swaps in the safe variant rather than pinning the argument, so `remember` is not in
    # the schema the model is given and there is nothing for it to ask for
    with pytest.raises(TypeError): fetch(url='https://example.com', remember=True)
    assert 'remember' not in inspect.signature(fetch).parameters

    seen.clear()
    writer = next(t for t in read_only(ts, writes=True) if t.__name__ == 'read_url')
    writer(url='https://example.com')
    assert seen == [True], 'an agent allowed writes keeps the default'


def test_the_trolley_writes_are_withheld_from_a_surface_that_may_not_act():
    """`cart_add` and `cart_remove` were named in `WRITE_TOOLS` and carried no `@writes`, and
    `read_only` reads the mark rather than the name. A read-only agent, and every read-only
    sub-agent, was handed the ability to change what someone is about to buy."""
    from shalya.core import is_write
    from ramabana.shop import Cart, cart_tools
    from ramabana.tools import WRITE_TOOLS, read_only

    ts = cart_tools(Cart())
    writing = {t.__name__ for t in ts if is_write(t)}
    assert writing == {'cart_add', 'cart_remove'}, writing
    assert writing <= WRITE_TOOLS, 'the mark and the name set have to agree'
    kept = {t.__name__ for t in read_only(ts)}
    assert not (kept & writing), f'a trolley write survived read_only: {sorted(kept & writing)}'
    assert 'cart_show' in kept and 'cart_find' in kept, 'looking is still allowed'
    assert not ({t.__name__ for t in read_only(ts, effects=False)} & writing)


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
