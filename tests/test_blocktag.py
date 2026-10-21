"A block printed while the transcript view is open during a turn already has its kind when the view repaints: `say` records it before `put` calls `on_change`."
import asyncio
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import Ui
from ramabana.testing import fake_agent


async def _slow(): await asyncio.sleep(.05)


def test_a_note_printed_with_the_transcript_open_mid_turn_does_not_crash():
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.start_turn(_slow())
        u.on_key(Key('ctrl+r'))
        assert u.transcript.active
        blk = u.say('a late note', 'note')
        assert u.kind(blk) == 'note'
        assert u.drillable() == []
        await asyncio.sleep(.1)
    try: asyncio.run(go())
    finally: tty.close()
