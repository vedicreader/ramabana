"Finished background work wakes an idle agent: the prompt, its modes and cap, and the terminal starting or deferring the turn."

import asyncio
from types import SimpleNamespace

from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana import cli
from ramabana.agent import Approvals
from ramabana.testing import fake_agent


def _finish(agent, state='completed', rid='run_x'):
    agent.background.on_done(SimpleNamespace(id=rid, state=state, question='q'), 'the answer')


def test_wake_prompt_modes_cancelled_and_cap():
    a, _ = fake_agent(approvals=Approvals(mode='auto'))
    assert a.wake_prompt() == ''
    _finish(a, 'cancelled')
    assert a.wake_prompt() == ''
    _finish(a)
    p = a.wake_prompt()
    assert 'run_x (completed)' in p and 'verify' in p
    assert len(a._bg_done) == 2, 'the notice, not the wake, drains what finished'
    a.auto_turns_per_hour = 1
    assert a.wake_prompt() == '', 'the hourly cap holds'

    r, _ = fake_agent(approvals=Approvals(mode='ask'))
    _finish(r)
    assert r.wake_mode() == 'report' and 'do not change files' in r.wake_prompt()

    o, _ = fake_agent(approvals=Approvals(mode='auto'), auto_turns='off')
    _finish(o)
    assert o.wake_prompt() == ''


def test_the_terminal_wakes_when_idle_and_defers_otherwise():
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent(replies=['woken', 'later'], approvals=Approvals(mode='auto'))

    async def scenario():
        await comp.start()
        ui = cli.Ui(comp, agent); ui.loop = asyncio.get_running_loop()
        ui._key_at -= 100

        ui.buf.insert('half a thought')
        _finish(agent)
        await asyncio.sleep(.05)
        assert ui._wake_pending and ui.turn is None, 'text in the composer defers the wake'

        ui.buf.clear()
        ui._maybe_wake()
        assert ui.turn is not None and not ui._wake_pending, 'an idle terminal starts the turn'
        for _ in range(80):
            await asyncio.sleep(.05)
            if ui.turn is None: break
        assert ui._reply.strip() == 'woken'

        _finish(agent, rid='run_y')
        ui.buf.insert('typing')
        ui._maybe_wake()
        assert ui._wake_pending
        ui.buf.clear()
        ui._next_queued()
        assert ui.turn is not None, 'the deferred wake fires when the turn queue is clear'
    try: asyncio.run(scenario())
    finally: tty.close()
