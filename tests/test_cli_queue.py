"A line typed while a turn is running: held, shown as held, and run when the turn ends."

import asyncio
import pytest
from teleprint.compositor import Compositor
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


def _said(u): return ' '.join(u.transcript.block_text(b) for b in u.comp.blocks.values())


def test_a_line_typed_during_a_turn_is_held_rather_than_dropped(ui):
    """`submit` clears the buffer and writes the line into the transcript before the turn is asked
    for, so closing the coroutine left a message that looked answered and was gone."""
    ran = []
    async def first():
        await asyncio.sleep(.05); ran.append('first')
    async def second(): ran.append('second')

    async def go():
        assert ui.start_turn(first()) is True
        assert ui.start_turn(second()) is False, 'the second one waits'
        assert ui._queued is not None, 'and it is kept, not closed'
        await asyncio.sleep(.2)
        return ran
    out = asyncio.run(go())
    assert out == ['first', 'second'], 'the held line runs once the turn it interrupted has ended'
    assert ui._queued is None


def test_the_surface_says_the_line_is_waiting(ui):
    async def slow(): await asyncio.sleep(.05)
    async def held(): pass
    async def go():
        ui.start_turn(slow()); ui.start_turn(held())
        assert 'queued' in _said(ui), 'a held line says so rather than looking answered'
        await asyncio.sleep(.2)
    asyncio.run(go())


def test_only_one_line_waits_and_the_first_one_keeps_the_slot(ui):
    """The newest used to win, so anything `on_key` handed back -- a `/python`, a `/promote`, this
    surface's own work -- silently evicted a message already waiting. Whoever got there keeps it,
    and the newcomer is told rather than swallowed."""
    ran = []
    async def slow(): await asyncio.sleep(.05)
    async def older(): ran.append('older')
    async def newer(): ran.append('newer')
    async def go():
        assert ui.start_turn(slow()) is True
        assert ui.start_turn(older()) is False
        assert ui.start_turn(newer()) is False
        await asyncio.sleep(.2)
    asyncio.run(go())
    assert ran == ['older'], 'the one that was waiting is the one that runs'
    assert 'already waiting' in _said(ui)


def test_stopping_clears_the_line_that_was_waiting(ui):
    "Ctrl-C means stop what is happening, and a line typed into it is part of that."
    async def slow(): await asyncio.sleep(.05)
    async def held(): raise AssertionError('a cleared line must not run')
    async def go():
        ui.start_turn(slow()); ui.start_turn(held())
        assert ui.drop_queued() is True and ui._queued is None
        assert ui.drop_queued() is False, 'and nothing is waiting the second time'
        await asyncio.sleep(.2)
    asyncio.run(go())
    assert 'cleared' in _said(ui)


def test_a_turn_that_has_already_ended_does_not_hold_the_next_one(ui):
    "`self.turn` outlives the coroutine, so a finished task must not look like a running turn."
    async def quick(): pass
    async def after(): pass
    async def go():
        ui.start_turn(quick())
        await asyncio.sleep(.05)
        assert ui.start_turn(after()) is True, 'the finished turn is not in the way'
        await asyncio.sleep(.05)
    asyncio.run(go())


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
        ui.buf.insert('two'); assert ui.start_turn(ui.submit()) is False, 'held, not started'
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
