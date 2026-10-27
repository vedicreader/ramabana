"A `!` line the user stops ends with `stopped`, even when the shell reports its killed child as status 128+N."

import asyncio
import pytest
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana.cli import Ui
from ramabana.testing import fake_agent


class _Killed:
    "A shell process whose child was killed: it prints the shell's message and exits 137, as `/bin/sh` does."
    pid, returncode = 999999, None
    def __init__(self, ui, stopped): self.ui, self.stopped = ui, stopped
    async def communicate(self):
        self.ui._shell_sigint = self.stopped   # what the user's ctrl+c sets while the command runs
        self.returncode = 137
        return b'/bin/sh: line 1: 4242 Killed: 9  sleep 30\n', None


@pytest.mark.parametrize('stopped, last', [(True, 'stopped'), (False, 'exit 137')])
def test_a_shell_that_reports_its_killed_child_ends_with_stopped_only_when_the_user_stopped_it(monkeypatch, stopped, last):
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    ui = Ui(comp, agent)
    async def fake_shell(*a, **kw): return _Killed(ui, stopped)
    monkeypatch.setattr(asyncio, 'create_subprocess_shell', fake_shell)
    try:
        asyncio.run(ui.run_shell_line('sleep 30'))
        blocks = [ui.transcript.block_text(b) for b in comp.blocks.values()]
        assert 'Killed: 9' in blocks[-2] and blocks[-1] == last, blocks[-3:]
    finally: tty.close()
