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


