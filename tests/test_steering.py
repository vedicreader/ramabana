"A line sent into a running turn: read after the root's next tool call, once, and never lost."

import asyncio
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import Ui
from ramabana.testing import ScriptedBackend, Step, fake_agent

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


def test_a_line_sent_after_the_last_call_is_left_over_not_lost():
    a, be = _scripted(Step(tool=READ), Step('the answer is here'))
    g = a.stream('go')
    next(g)                                   # the call has returned: the answer is streaming
    assert a.steer('one more thing')
    list(g)
    assert 'user-message' not in _tool_results(be)[0]
    assert a.leftovers() == ['one more thing']
    assert a.leftovers() == [], 'taken once'


# the surface


def _type(u, text, key='enter'):
    "Type a line and press `key`, handing any coroutine to `start_turn` as the main loop does."
    u.buf.insert(text)
    if (out := u.on_key(Key(key))) is not None: u.start_turn(out)
    return out


async def _slow(): await asyncio.sleep(.05)


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


def test_an_attached_line_steers_and_enter_on_an_empty_line_steers_the_queued_one(tmp_path):
    """A pasted picture sent the line to the queue, where it waited out a forty-minute turn, and a
    queued line had no way into the running turn. The picture travels by path; Enter on an empty
    line hands the queued line to the turn."""
    from ramabana.tools import Attachment
    (pic := tmp_path/'shot.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 20)
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = _scripted(Step('looking'), Step(tool=READ, pause=.5), Step(tool=READ, pause=.5), Step('done'))
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        _type(u, 'read a.py')
        for _ in range(40):
            await asyncio.sleep(.02)
            if (r := agent.run()) is not None and not r.terminal: break
        u.attachments.append(Attachment(pic))
        assert _type(u, 'look at this too') is None and u._queued is None and u.attachments == [], 'steered, not queued'
        _type(u, 'and then b.py', 'alt+enter')
        assert u._queued is not None
        assert _type(u, '') is None and u._queued is None, 'enter on an empty line steers the queued line'
        for _ in range(100):
            await asyncio.sleep(.05)
            if u.turn is None: break
    try:
        asyncio.run(go())
        read = '\n'.join(_tool_results(be))
        assert 'look at this too' in read and str(pic) in read and 'and then b.py' in read
        assert len(be.sent) == 1, 'read in the turn, not run as another'
    finally: tty.close()
