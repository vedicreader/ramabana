"A line queued during a turn (alt+enter, or Enter with no root run to steer): held, shown as held, and run when the turn ends."

import asyncio
import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import Ui
from ramabana.testing import fake_agent


@pytest.fixture
def ui():
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    yield Ui(comp, agent)
    tty.close()


def _surface(replies):
    "A whole CLI over an emulated terminal, with a real loop under it."
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana import cli
    from ramabana.testing import fake_agent
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    return tty, comp, cli, fake_agent(replies=replies)


def test_the_message_typed_during_a_turn_actually_runs_when_it_ends():
    """The slot was covered but the drain was not: the old test asserted the coroutine was held and
    then dropped it, so nothing ever checked that a queued line reaches the model."""
    import asyncio
    tty, comp, cli, (agent, _) = _surface(['first answer', 'second answer'])

    async def scenario():
        await comp.start()
        ui = cli.Ui(comp, agent); ui.loop = asyncio.get_running_loop()
        # both lines before yielding to the loop, so the first turn is certainly still in flight:
        # the fake agent answers instantly and a sleep here raced it
        ui.buf.insert('one'); assert ui.start_turn(ui.submit()) is True
        ui.buf.insert('two'); assert ui.start_turn(ui.on_key(Key('alt+enter'))) is False, 'held, not started'
        assert ui._queued is not None
        for _ in range(80):
            await asyncio.sleep(.05)
            if ui._queued is None and ui.turn is None: break
        assert ui._queued is None, 'the waiting message was never drained'
        assert ui._reply == 'second answer ', f'the queued turn did not run: {ui._reply!r}'
    try: asyncio.run(scenario())
    finally: tty.close()


@pytest.mark.parametrize('at_handoff', [False, True])
def test_finished_queue_does_not_absorb_the_next_message(at_handoff):
    tty, comp, cli, (agent, backend) = _surface(['first answer', 'a answer', 'b answer'])

    async def scenario():
        await comp.start()
        u = cli.Ui(comp, agent, loop=asyncio.get_running_loop())
        _type(u, 'first')
        _type(u, 'a', 'alt+enter')
        if at_handoff:
            # A ready key event can run before the completed task's done callback.
            paint = u.paint
            def at_completion():
                paint()
                if agent.run() is not None and agent.run().terminal:
                    u.paint = paint
                    asyncio.get_running_loop().call_soon(_type, u, 'b', 'alt+enter')
            u.paint = at_completion
        for _ in range(100):
            await asyncio.sleep(.01)
            if u.turn is None and u._queued is None: break
        assert u._queued is None and u.queued_rows() == []
        if not at_handoff:
            assert [msg.removeprefix('<user-request>\n').removesuffix('\n</user-request>') for msg in backend.sent] == ['first', 'a']
            _type(u, 'b', 'alt+enter')
            for _ in range(100):
                await asyncio.sleep(.01)
                if u.turn is None and u._queued is None: break
        assert [msg.removeprefix('<user-request>\n').removesuffix('\n</user-request>') for msg in backend.sent] == ['first', 'a', 'b']
        assert u.queued_rows() == []
        assert [blk.source for blk in comp.blocks.values() if u.kind(blk) == 'user'] == ['first', 'a', 'b']
    try: asyncio.run(scenario())
    finally: tty.close()


def test_this_surfaces_own_work_cannot_evict_a_waiting_message(ui):
    """A surface command that starts work of its own, typed during a turn, used to take the slot the
    message was in, run itself when the turn ended, and leave the line gone with nothing saying so."""
    ran = []
    async def slow(): await asyncio.sleep(.05)
    async def my_message(): ran.append('my message')
    async def surface_work(): ran.append('surface work')
    async def go():
        ui.start_turn(slow())
        mine = my_message()
        assert ui.start_turn(mine) is False and ui._queued is mine
        assert ui.start_turn(surface_work()) is False
        assert ui._queued is mine, 'the message is still the one waiting'
        await asyncio.sleep(.2)
    asyncio.run(go())
    assert ran == ['my message']


def test_both_lines_reach_the_model_as_one_message():
    "The merge is only real if the ask carries both. One turn, one message, both lines in it."
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, be = fake_agent()
    u = Ui(comp, agent)
    async def slow(): await asyncio.sleep(.05)
    async def go():
        u.start_turn(slow())
        u.start_turn(u._turn('look at the tests'))
        u.start_turn(u._turn('and the lockfile'))
        await asyncio.sleep(.6)      # the turn ends, the drain runs the merged one
    try:
        asyncio.run(go())
        assert len(be.sent) == 1, f'one turn, not {len(be.sent)}'
        assert 'look at the tests' in str(be.sent[0]) and 'and the lockfile' in str(be.sent[0])
    finally: tty.close()


def _type(u, text, key='enter'):
    "Type a line and press `key`, handing any coroutine to `start_turn` as the main loop does."
    u.buf.insert(text)
    if (out := u.on_key(Key(key))) is not None: u.start_turn(out)
    return out


async def _slow(): await asyncio.sleep(.05)


def _scene(body):
    "Run `await body(ui, agent)` on a live loop over an emulated terminal; its asserts surface here."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        await body(u, agent)
    try: asyncio.run(go())
    finally: tty.close()


def test_stop_returns_unread_steering_queued_lines_and_the_draft_to_the_composer():
    "Ctrl-C used to wipe all three; the user typed them, so they come back in the order they were said."
    async def body(u, agent):
        u.start_turn(_slow())
        agent._new_run('q')
        _type(u, 'steer that was never read')
        _type(u, 'first queued', 'alt+enter')
        _type(u, 'second queued', 'alt+enter')
        u.buf.insert('half typed')
        u.stop()
        assert u.buf.text == 'steer that was never read\n\nfirst queued\n\nsecond queued\n\nhalf typed'
        assert u._queued is None and u._queued_prompt is None and agent.leftovers() == []
    _scene(body)


def _steer_scene(body):
    "Like `_scene`, but `body(ui, agent, tty)` also gets the emulated terminal, to read the painted rows."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        await body(u, agent, tty)
    try: asyncio.run(go())
    finally: tty.close()


def test_a_steered_line_waits_in_the_rows_until_the_agent_reads_it():
    "Steering showed only as a transcript echo; the unread line is also a row, and leaves it when the inbox is drained."
    async def body(u, agent, tty):
        u.start_turn(_slow())
        run = agent._new_run('q')
        _type(u, 'two')
        _type(u, 'later', 'alt+enter')
        u.paint()
        screen = tty.term.text()
        rows = [r.plain for r in u.queued_rows()]
        assert len(rows) == 2 and 'two' in rows[0] and 'unread' in rows[0] and 'later' in rows[1] and 'queued' in rows[1]
        assert 'unread' in screen and 'two' in screen
        assert run.drain_inbox() == ['two']                # what the root tool result does
        assert [r.plain for r in u.queued_rows()] == [rows[1]], 'read: no longer waiting, the queued line stays'
        u.paint()
        assert 'unread' not in tty.term.text()
    _steer_scene(body)


def test_an_unread_row_does_not_offer_to_steer_a_line_already_steered():
    "The last row carried 'enter steers it into this turn' even when it was a steered line, which Enter cannot send again."
    async def body(u, agent, tty):
        u.start_turn(_slow())
        agent._new_run('q')
        _type(u, 'two')
        [row] = [r.plain for r in u.queued_rows()]
        assert 'unread' in row and 'enter steers' not in row and 'alt+up' in row, row
    _steer_scene(body)


def test_take_back_returns_an_unread_steered_line_to_the_composer():
    async def body(u, agent, tty):
        u.start_turn(_slow())
        agent._new_run('q')
        _type(u, 'two')
        assert u.on_key(Key('alt+up')) is None
        assert u.buf.text == 'two' and u.queued_rows() == [] and agent.leftovers() == []
    _steer_scene(body)


def test_ctrl_c_keeps_the_draft_in_the_composer():
    async def body(u, agent):
        u.start_turn(_slow())
        agent._new_run('q')
        u.buf.insert('half typed')
        u.on_key(Key('ctrl+c'))
        assert u.buf.text == 'half typed'
    _scene(body)


def test_alt_up_pulls_the_queued_text_back_and_the_turn_keeps_running():
    async def body(u, agent):
        u.start_turn(_slow())
        _type(u, 'first queued', 'alt+enter')
        _type(u, 'second queued', 'alt+enter')
        u.buf.insert('draft')
        assert u.on_key(Key('alt+up')) is None
        assert u.buf.text == 'first queued\n\nsecond queued\n\ndraft'
        assert u._queued is None and u.queued_rows() == [] and u.turn is not None
    _scene(body)


def test_up_recalls_one_queued_line_newest_first_and_clearing_cancels():
    async def body(u, agent):
        u.start_turn(_slow())
        _type(u, 'a', 'alt+enter')
        _type(u, 'b', 'alt+enter')
        u.on_key(Key('up'))
        assert u.buf.text == 'b' and u._queued_prompt == 'a'
        assert '↑' in u.footer_hint()
        assert not u.transcript.active
        assert len(u.queued_rows()) == 1
        u.on_key(Key('ctrl+u'))
        u.on_key(Key('up'))
        assert u.buf.text == 'a' and u._queued is None
        u.on_key(Key('ctrl+u'))
        await asyncio.sleep(.15)
        assert agent._be().sent == []
        assert u.queued_rows() == []
    _scene(body)


def test_up_recalls_newest_unread_atomically_and_edit_sends_once():
    async def body(u, agent, tty):
        u.start_turn(_slow())
        run = agent._new_run('q')
        _type(u, 'older queued', 'alt+enter')
        _type(u, 'newer unread')
        _type(u, 'newest queued', 'alt+enter')
        u.on_key(Key('up'))
        assert u.buf.text == 'newest queued' and u._queued_prompt == 'older queued'
        u.on_key(Key('ctrl+u'))
        u.on_key(Key('up'))
        assert u.buf.text == 'newer unread' and not u.transcript.active
        assert run.drain_inbox() == []
        assert u._queued_prompt == 'older queued'
        u.on_key(Key('ctrl+u'))
        _type(u, 'edited')
        assert run.drain_inbox() == ['edited']
        assert run.drain_inbox() == []
        u.on_key(Key('alt+up'))
        u.on_key(Key('ctrl+u'))
        await asyncio.sleep(.15)
    _steer_scene(body)


def test_up_with_a_draft_does_not_recall_waiting_text():
    async def body(u, agent):
        u.start_turn(_slow())
        _type(u, 'waiting', 'alt+enter')
        u.buf.insert('draft')
        u.on_key(Key('up'))
        assert u.buf.text == 'draft' and u._queued_prompt == 'waiting'
        u.take_back()
    _scene(body)


