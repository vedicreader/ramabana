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


def test_the_key_never_reaches_a_looser_mode_however_often_it_is_pressed(ui):
    for _ in range(10): ui.tighten_approve()
    assert ui.agent.approvals.mode == 'off'


def test_the_key_is_bound_and_reaches_the_control(ui):
    class _Key:
        name = 'ctrl+g'
    ui.agent.approvals.mode = 'auto'
    ui.on_key(_Key())
    assert ui.agent.approvals.mode == 'edits', 'ctrl+g did not reach tighten_approve'
