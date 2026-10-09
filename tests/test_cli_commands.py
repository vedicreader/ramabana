"""Skills as slash commands, `#note`, the always-allow key, and the one-shot JSON path."""
import io, json, sys

from ramabana.cli import ask_once, headless_prompt
from ramabana.testing import fake_agent


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
