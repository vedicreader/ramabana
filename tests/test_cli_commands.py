"""Skills as slash commands, `#note`, the always-allow key, and the one-shot JSON path."""
import asyncio, io, json, sys

import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.agent import Approvals, Ask
from ramabana.cli import Ui, ask_once, ask_pattern, headless_prompt
from ramabana.testing import fake_agent
from ramabana.tools import WRITE_TOOLS


@pytest.fixture
def ui(tmp_path):
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent(cfg=tmp_path)
    agent.approvals = Approvals(tools=WRITE_TOOLS, mode='ask')
    yield Ui(comp, agent)
    tty.close()


def _said(u): return ' '.join(u.transcript.block_text(b) for b in u.comp.blocks.values())

def _submit(u, line):
    u.buf.text = line
    out = u.submit()
    if asyncio.iscoroutine(out): out.close()
    return out


def test_a_skill_name_typed_as_a_command_becomes_a_prompt_with_the_skill_attached(ui):
    name = next(s.name for s in ui.agent.skills)
    assert asyncio.iscoroutine(_submit(ui, f'/{name} fix the loop')), 'a turn, not an error'
    assert ui._prompt == f'/{name} fix the loop', 'the line itself is the prompt: `prompt_directives` loads the skill from it'
    _submit(ui, '/nosuchthing at all')
    assert 'unknown command' in _said(ui)


def test_a_commands_file_is_a_prompt_with_its_arguments_filled_in(ui, tmp_path):
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'hello.md').write_text('Greet $ARGUMENTS warmly.\n')
    assert asyncio.iscoroutine(_submit(ui, '/hello the world'))
    assert ui._prompt == 'Greet the world warmly.'
    assert ui.skill_command('nosuch', 'x') is None


def test_a_note_goes_to_the_agent_when_it_can_keep_one(ui):
    _submit(ui, '#note')
    assert 'usage: #note' in _said(ui)
    _submit(ui, '#note prefer uv')
    assert 'prefer uv' in ui.agent.memory_path.read_text()


def test_the_always_key_keeps_a_rule_and_approves(ui):
    answers = []
    ui.answer = lambda ok, session=False: answers.append((ok, session))
    ui.ask = Ask(tool='run_shell', args={'command': 'pytest -q'})
    ui.on_key(Key('A', 'A'))
    assert answers == [(True, False)] and ui.agent.approvals.rule_for('run_shell', {'command': 'pytest -q'}) == 'allow'
    assert ask_pattern(Ask(tool='edit_file', args={'path': 'a.py'})) == 'a.py'


def test_a_one_shot_prompt_can_come_from_stdin_and_go_out_as_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('from a pipe\n'))
    assert headless_prompt('-') == 'from a pipe'
    assert headless_prompt('typed') == 'typed'
    agent, _ = fake_agent(replies=['pong'])
    assert ask_once(agent, 'ping', as_json=True) == 0
    got = json.loads(capsys.readouterr().out)
    assert got['reply'] == 'pong' and got['session'] == agent.session_id
    assert set(got) == {'reply', 'usage', 'changes', 'activity', 'problems', 'session'}
    assert isinstance(got['usage'], dict) and got['changes'] == [] and got['problems'] == []
