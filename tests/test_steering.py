"A line sent into a running turn: read after the root's next tool call, once, and never lost."

import asyncio
import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import Ui
from ramabana.runtime import run_context
from ramabana.testing import ScriptedBackend, Step, fake_agent
from ramabana.tools import inbox_note

READ = ('view_file', {'path': '/proj/a.py'})


def _scripted(*steps):
    "An agent whose turn walks `steps`, calling its own recorded tools."
    a, _ = fake_agent()
    be = ScriptedBackend(steps=list(steps), token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


def _tool_results(be): return [m['content'] for m in be.hist_ if m['role'] == 'tool']


def _tag(a, *lines): return f'<user-message key="{a.inbox_key}">\n' + '\n'.join(lines) + '\n</user-message>'


def test_a_line_sent_mid_turn_reaches_the_next_root_tool_result_exactly_once():
    a, be = _scripted(Step('looking'), Step(tool=READ), Step(tool=READ), Step('done'))
    g = a.stream('go')
    next(g)                                   # the turn is running, before its first call
    assert a.steer('check the tests too')
    list(g)
    first, second = _tool_results(be)
    assert 'def a' in first, 'the tool still answered'
    assert first.endswith(_tag(a, 'check the tests too'))
    assert 'user-message' not in second, 'read once, not on every later call'
    assert a.leftovers() == []


def test_two_lines_before_a_call_arrive_together():
    a, be = _scripted(Step('looking'), Step(tool=READ), Step('done'))
    g = a.stream('go')
    next(g)
    a.steer('one'); a.steer('two')
    list(g)
    assert _tool_results(be)[0].endswith(_tag(a, 'one', 'two'))


def test_the_root_briefing_carries_one_key_for_the_whole_session():
    "The system prompt is cached, so a per-turn key would name a tag the model was never told about."
    a, _ = _scripted(Step('ok'))
    assert inbox_note(a.inbox_key) in a.system_prompt()
    list(a.stream('one')); first = a.run()
    list(a.stream('two')); second = a.run()
    assert first is not second and first.key == second.key == a.inbox_key
    assert inbox_note(a.inbox_key) in a.system_prompt()


def test_a_sub_agents_call_leaves_the_root_inbox_alone():
    "Sub-agents may share the root's tools; only the root's own call may take its messages."
    a, _ = fake_agent()
    view = next(t for t in a.tools if t.__name__ == 'view_file')
    root = a._new_run('q')
    child = root.child('sub question')
    assert child.key != a.inbox_key, 'a sub-agent run keeps its own key'
    assert a.steer('for the root')
    with run_context(child): assert 'user-message' not in view('/proj/a.py')
    with run_context(root): assert view('/proj/a.py').endswith(_tag(a, 'for the root'))
    root.finish()


def test_steering_needs_a_running_root_turn():
    a, _ = _scripted(Step('ok'))
    assert not a.steer('nobody is listening')
    list(a.stream('go'))
    assert not a.steer('the turn is over')
    run = a._new_run('q')
    assert not a.steer('   '), 'nothing to say'
    run.cancel(0)
    assert not a.steer('stopping means stop')
    assert a.leftovers() == []


def test_a_line_sent_after_the_last_call_is_left_over_not_lost():
    a, be = _scripted(Step(tool=READ), Step('the answer is here'))
    g = a.stream('go')
    next(g)                                   # the call has returned: the answer is streaming
    assert a.steer('one more thing')
    list(g)
    assert 'user-message' not in _tool_results(be)[0]
    assert a.leftovers() == ['one more thing']
    assert a.leftovers() == [], 'taken once'


def test_tell_still_reaches_sub_agent_runs():
    a, _ = fake_agent()
    root = a._new_run('q')
    child = root.child('sub question')
    assert a.tell(child.id, 'look at b') == f'told {child.id}'
    assert child.drain_inbox() == ['look at b'] and root.drain_inbox() == []
    root.finish()


# the surface


@pytest.fixture
def ui():
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    yield Ui(comp, agent)
    tty.close()


def _said(u): return ' '.join(u.transcript.block_text(b) for b in u.comp.blocks.values())


def _rows(u):
    rs, _ = u.tail()
    return [r.plain if hasattr(r, 'plain') else str(r) for r in rs]


def _type(u, text, key='enter'):
    "Type a line and press `key`, handing any coroutine to `start_turn` as the main loop does."
    u.buf.insert(text)
    if (out := u.on_key(Key(key))) is not None: u.start_turn(out)
    return out


async def _slow(): await asyncio.sleep(.05)


def test_enter_mid_turn_steers_the_running_root(ui):
    async def go():
        ui.start_turn(_slow())
        run = ui.agent._new_run('q')
        assert _type(ui, 'also check the tests') is None
        assert run.inbox == ['also check the tests'], 'told, not queued'
        assert ui._queued is None and not [r for r in _rows(ui) if '⏳' in r]
        assert '↪ also check the tests' in _said(ui), 'echoed, marked as steering'
        assert [r for r in _rows(ui) if 'sent · read after the current call' in r], _rows(ui)
        run.drain_inbox(); run.finish()
        await asyncio.sleep(.1)
    asyncio.run(go())


def test_alt_enter_mid_turn_queues_as_the_next_turn(ui):
    async def go():
        ui.start_turn(_slow())
        run = ui.agent._new_run('q')
        _type(ui, 'look at the tests', 'alt+enter')
        _type(ui, 'and the lockfile', 'alt+enter')
        assert run.inbox == [], 'nothing reached the running turn'
        assert ui._queued_prompt == 'look at the tests\n\nand the lockfile'
        ui.drop_queued(); run.finish()
        await asyncio.sleep(.1)
    asyncio.run(go())


def test_a_command_mid_turn_is_not_steering(ui):
    async def go():
        ui.start_turn(_slow())
        run = ui.agent._new_run('q')
        _type(ui, '/runs')
        assert run.inbox == [] and ui._queued is None
        assert run.id in _said(ui), 'the command answered as it always did'
        run.finish()
        await asyncio.sleep(.1)
    asyncio.run(go())


def test_enter_with_no_root_run_to_steer_falls_back_to_the_queue(ui):
    async def go():
        ui.start_turn(_slow())                # a turn is up but the agent has no running root
        _type(ui, 'look at the tests')
        assert ui._queued_prompt == 'look at the tests'
        ui.drop_queued()
        await asyncio.sleep(.1)
    asyncio.run(go())


def test_stopping_clears_the_queue_and_unread_steering(ui):
    async def go():
        ui.start_turn(_slow())
        run = ui.agent._new_run('q')
        _type(ui, 'steer this')
        _type(ui, 'and queue this', 'alt+enter')
        ui.on_key(Key('ctrl+c'))
        assert ui._queued is None and run.inbox == [], 'stopping means stop'
        await asyncio.sleep(.3)
        assert ui.agent.leftovers() == []
    asyncio.run(go())


def test_unread_steering_runs_as_the_next_turn_joined_with_the_queue():
    "What the turn never read is still what the user said: it becomes the next turn, ahead of the queued line."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = fake_agent(replies=['after'])
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.start_turn(_slow())
        run = agent._new_run('q')
        _type(u, 'steer that was never read')
        _type(u, 'queued line', 'alt+enter')
        run.finish()                          # it ended without another tool call
        for _ in range(60):
            await asyncio.sleep(.05)
            if be.sent and u.turn is None: break
        return u
    try:
        u = asyncio.run(go())
        assert len(be.sent) == 1, be.sent
        sent = str(be.sent[0])
        assert 'steer that was never read' in sent and 'queued line' in sent
        assert sent.index('steer that was never read') < sent.index('queued line')
        assert u._queued is None and agent.leftovers() == []
    finally: tty.close()


def test_unread_steering_alone_becomes_the_next_turn():
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = fake_agent(replies=['after'])
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.start_turn(_slow())
        run = agent._new_run('q')
        _type(u, 'left over')
        assert run.inbox == ['left over'] and u._queued is None, 'steered, not queued'
        run.finish()
        for _ in range(60):
            await asyncio.sleep(.05)
            if be.sent and u.turn is None: break
    try:
        asyncio.run(go())
        assert len(be.sent) == 1 and 'left over' in str(be.sent[0])
    finally: tty.close()


def test_enter_during_a_real_turn_lands_in_its_next_tool_result():
    "The whole path: a keystroke on the surface, the agent's inbox, the root tool's result the model reads."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = _scripted(Step('looking'), Step(tool=READ, pause=.5), Step('done'))
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        _type(u, 'read a.py')
        for _ in range(40):
            await asyncio.sleep(.02)
            if (r := agent.run()) is not None and not r.terminal: break
        assert _type(u, 'and mention b.py') is None
        for _ in range(100):
            await asyncio.sleep(.05)
            if u.turn is None: break
    try:
        asyncio.run(go())
        assert _tool_results(be)[0].endswith(_tag(agent, 'and mention b.py'))
        assert len(be.sent) == 1, 'read in the turn, not run as another'
    finally: tty.close()
