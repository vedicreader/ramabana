"""Changing the approvals policy mid-session, from a key and from a command.

The two directions are not alike. Tightening is bound to a key, so it has to be safe to hit by
accident. Loosening is typed, which is the rule the code already held: the policy comes off only
when somebody meant it.
"""
import asyncio

import pytest
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana.agent import Approvals
from ramabana.cli import Ui
from ramabana.testing import fake_agent
from ramabana.tools import WRITE_TOOLS


@pytest.fixture
def ui():
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    agent.approvals = Approvals(tools=WRITE_TOOLS, mode='ask')
    yield Ui(comp, agent)
    tty.close()


def test_the_key_tightens_from_every_mode_and_never_loosens(ui):
    ui.agent.approvals.mode = 'auto'
    assert ui.tighten_approve() == 'approvals: auto -> edits'
    assert ui.tighten_approve() == 'approvals: edits -> ask'
    assert ui.agent.approvals.mode == 'ask'
    assert ui.tighten_approve() == 'approvals: ask -> off'
    assert ui.agent.approvals.mode == 'off'
    # the last step is a wall rather than a wrap: a key must not be able to turn the gate off
    assert 'off' in ui.tighten_approve()
    assert ui.agent.approvals.mode == 'off'
