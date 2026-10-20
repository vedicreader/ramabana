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


# read receipts


def _src(blk): return blk.source or ''


def test_a_steered_line_gets_its_receipt_only_after_it_left_the_inbox():
    "The echo says sent; a check mark waits until the model's call drained it from the run's inbox."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = fake_agent(replies=['after'])
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.start_turn(_slow())
        run = agent._new_run('q')
        _type(u, 'check the tests too')
        (_, blk), = u._steered
        assert '✓' not in _src(blk), 'sent is not read'
        u.mark_read()
        assert '✓' not in _src(blk) and len(u._steered) == 1, 'still in the inbox: still unread'
        assert run.drain_inbox() == ['check the tests too']      # what the root tool result does
        _type(u, 'check the tests too')
        _, later = u._steered[-1]
        u.mark_read()
        assert '✓' in _src(blk) and '✓' not in _src(later)
        assert len(u._steered) == 1
        run.drain_inbox()
        u.mark_read()
        assert '✓' in _src(later) and u._steered == []
    try: asyncio.run(go())
    finally: tty.close()


def test_a_line_the_turn_ended_without_reading_never_gets_a_receipt():
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = fake_agent(replies=['after'])
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.start_turn(_slow())
        agent._new_run('q')
        _type(u, 'too late')
        (_, blk), = u._steered
        u.mark_read(final=True)                       # the turn is over and the line is still in the inbox
        assert '✓' not in _src(blk) and u._steered == []
        assert agent.leftovers() == ['too late']
    try: asyncio.run(go())
    finally: tty.close()


def test_a_real_turn_marks_the_steered_line_read():
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, be = _scripted(Step('looking'), Step(tool=READ, pause=.3), Step('done'))
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        _type(u, 'read a.py')
        for _ in range(40):
            await asyncio.sleep(.02)
            if (r := agent.run()) is not None and not r.terminal: break
        assert _type(u, 'and mention b.py') is None
        (_, blk), = u._steered
        assert '✓' not in _src(blk)
        for _ in range(100):
            await asyncio.sleep(.05)
            if u.turn is None: break
        return blk
    try:
        blk = asyncio.run(go())
        assert _tool_results(be)[0].endswith(_tag(agent, 'and mention b.py'))
        assert '✓' in _src(blk)
    finally: tty.close()


def test_queued_prompts_run_in_order_and_unread_steering_joins_the_next_turn(tmp_path):
    "A host queues follow-ups while a job runs; a line that arrived after the last tool call is not left for it to find."
    a, be = fake_agent(cfg=tmp_path, replies=['one', 'two', 'three'])
    a.ask('first')
    a.run().tell('also check the footnotes')        # arrived after the turn's last tool result
    assert a.queue('second') == 1 and a.queue('third') == 2
    results = a.run_queued()
    assert [r.reply for r in results] == ['two', 'three'] and all(r.state == 'complete' for r in results)
    assert 'also check the footnotes' in str(be.sent[1]) and 'second' in str(be.sent[1]), 'the unread line joins the next turn'
    assert 'footnotes' not in str(be.sent[2]) and not a.queued and a.run_queued() == []


def test_a_line_sent_during_a_result_at_the_cap_survives_the_backends_cut():
    "A result filling the cap, a wide delegation or a clipped file, lost the line appended after it: the backend cut it off."
    a, _ = fake_agent()
    def big() -> str:
        "A result as long as a result may be."
        return 'x' * a.budget.tool_max
    a.add_tool(big)
    be = ScriptedBackend(steps=[Step('looking'), Step(tool=('big', {})), Step('done')], token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    got, find = [], be._tool
    be._tool = lambda name: (lambda f: lambda **kw: got.append(f(**kw)) or got[-1])(find(name))   # the whole result, not the hist's head
    g = a.stream('go')
    next(g)
    assert a.steer('also pull the new release')
    list(g)
    out, = got
    assert len(out) <= a.budget.tool_max, 'the backend cuts anything longer from the end'
    assert out.endswith(_tag(a, 'also pull the new release'))
    assert 'full text saved to' in out, 'the body gave way, and says where the rest is'


def test_a_line_longer_than_the_cap_still_arrives_and_names_where_the_rest_is():
    from ramabana.runtime import Run
    from ramabana.tools import _inboxed
    r = Run('r'); r.tell('y' * 5000)
    out = _inboxed(lambda: 'z' * 3000, r, mx=lambda: 4000)()
    assert len(out) <= 4000 and out.endswith('</user-message>') and out.count('full text saved to') == 2
