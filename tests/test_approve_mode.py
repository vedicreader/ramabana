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
from ramabana.cli import APPROVE_MODES, Ui
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


def test_the_modes_run_strictest_first_so_tightening_is_one_step_back():
    assert APPROVE_MODES == ('off', 'ask', 'auto')


def test_the_key_tightens_from_every_mode_and_never_loosens(ui):
    ui.agent.approvals.mode = 'auto'
    assert ui.tighten_approve() == 'approvals: auto -> ask'
    assert ui.agent.approvals.mode == 'ask'
    assert ui.tighten_approve() == 'approvals: ask -> off'
    assert ui.agent.approvals.mode == 'off'
    # the last step is a wall rather than a wrap: a key must not be able to turn the gate off
    assert 'off' in ui.tighten_approve()
    assert ui.agent.approvals.mode == 'off'


def test_the_key_never_reaches_a_looser_mode_however_often_it_is_pressed(ui):
    for _ in range(10): ui.tighten_approve()
    assert ui.agent.approvals.mode == 'off'


def test_the_command_is_the_only_way_back_to_a_looser_mode(ui):
    ui.agent.approvals.mode = 'off'
    assert ui.approve_mode('ask') == 'approvals: off -> ask'
    assert ui.agent.approvals.mode == 'ask'
    assert ui.approve_mode('auto') == 'approvals: ask -> auto'
    assert ui.agent.approvals.mode == 'auto'


def test_the_command_with_no_argument_reports_rather_than_changing(ui):
    assert ui.approve_mode() == 'approvals: ask'
    assert ui.agent.approvals.mode == 'ask'
    assert ui.approve_mode('') == 'approvals: ask'


def test_a_mode_nobody_defined_is_refused_with_the_usage_line(ui):
    assert ui.approve_mode('yolo') == 'usage: /approve [off|ask|auto]'
    assert ui.agent.approvals.mode == 'ask', 'a rejected mode changed the policy anyway'


def test_a_session_without_approvals_says_so_rather_than_raising(ui):
    ui.agent.approvals = None
    assert ui.tighten_approve() == 'this session runs without approvals'
    assert ui.approve_mode('auto') == 'this session runs without approvals'


def test_the_key_is_bound_and_reaches_the_control(ui):
    class _Key:
        name = 'ctrl+g'
    ui.agent.approvals.mode = 'auto'
    ui.on_key(_Key())
    assert ui.agent.approvals.mode == 'ask', 'ctrl+g did not reach tighten_approve'


def test_the_command_is_registered_so_tab_completion_offers_it():
    from ramabana.cli import SURFACE_COMMANDS
    assert 'approve' in SURFACE_COMMANDS


def test_the_status_a_frontend_renders_carries_the_mode(ui):
    assert ui.agent.status()['approve'] == 'ask'
    ui.approve_mode('off')
    assert ui.agent.status()['approve'] == 'off'
