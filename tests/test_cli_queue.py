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


def test_this_surfaces_own_work_cannot_evict_a_waiting_message(ui):
    """A `/python` or `/promote` typed during a turn used to take the slot the message was in, run
    itself when the turn ended, and leave the line gone with nothing saying so."""
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
        assert len([r for r in u.queued_rows()]) == 2, 'one row per queued line'
        u.buf.insert('draft')
        assert u.on_key(Key('alt+up')) is None
        assert u.buf.text == 'first queued\n\nsecond queued\n\ndraft'
        assert u._queued is None and u.queued_rows() == [] and u.turn is not None
    _scene(body)


def test_a_refused_slash_command_stays_in_the_composer():
    "The line was cleared from the buffer before the loop learned the slot was taken, so its text was lost."
    async def body(u, agent):
        u.start_turn(_slow())
        _type(u, 'first', 'alt+enter')
        assert _type(u, '/python') is not None
        assert u.buf.text == '/python' and u._queued_prompt == 'first'
    _scene(body)


