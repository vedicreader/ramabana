"""Extensions and the command surface: what an application may add, and what both frontends share.

An IDE that will not open because of a stray file in a config directory is a worse IDE, so the
theme here is that everything an extension can get wrong is reported rather than raised.
"""
import pytest

from ramabana import agent, core
from ramabana.testing import fake_agent
from ramabana.tools import Registry, load


def test_an_extension_may_add_a_tool_a_skill_and_a_command_and_never_crash_the_session(tmp_path):
    """Project extensions are off unless asked for, because a file in a repository you cloned five
    minutes ago runs arbitrary Python with the agent's tools. An unknown hook name is an error at
    registration rather than a silent no-op at fire time."""
    d = tmp_path/'extensions'
    d.mkdir(parents=True)
    (d/'mine.py').write_text(
        'def setup(ext):\n'
        '    @ext.tool\n'
        '    def count_todos(path: str) -> str:\n'
        '        "Count TODOs."\n'
        '        return "3"\n'
        '    ext.skill("house-style", "we write it like this", "How we write code here")\n'
        '    ext.command("hi", lambda agent, arg: f"hello {arg}", "say hi")\n')
    reg = load(Registry(), cfg=tmp_path)
    assert [t.__name__ for t in reg.tools] == ['count_todos']
    assert reg.skills[0].name == 'house-style'
    assert reg.commands['hi'][0](None, 'you') == 'hello you'
    assert 'mine.py: 1 tool(s), 1 skill(s), 1 command(s)' in reg.notes

    (d/'mine.py').unlink()
    (d/'bad.py').write_text('raise RuntimeError("boom")\n')
    broken = load(Registry(), cfg=tmp_path)
    assert broken.tools == [] and any('boom' in n for n in broken.notes)

    proj = tmp_path/'.leela'/'extensions'
    proj.mkdir(parents=True)
    (proj/'x.py').write_text('def setup(ext):\n    ext.command("boom", lambda a, b: "", "")\n')
    assert load(Registry(), roots=[tmp_path]).commands == {}
    assert 'boom' in load(Registry(), roots=[tmp_path], project=True).commands

    with pytest.raises(KeyError): Registry().on('after_lunch', lambda: None)


def test_the_commands_exist_once_for_both_frontends_and_report_the_whole_policy(monkeypatch):
    "A command defined per frontend is a command that behaves differently in the terminal and the IDE."
    a, _ = fake_agent()
    assert {'model', 'cost', 'compact', 'skills', 'tools', 'reload'} <= set(a.commands())
    assert a.command('nonsense') is None
    assert a.command('cost') is not None

    out = a.command('model')
    for job in core.JOBS: assert job in out, job

    monkeypatch.setattr(agent, 'available_models', lambda include_legacy=False: [
        {'value': 'gemma-e4b', 'provider': 'litert', 'source': 'on device'},
        {'value': 'claude_code/claude-sonnet-4-6', 'provider': 'claude_code',
         'source': 'Claude Code login'}])
    models = a.command('/models')
    assert 'gemma-e4b' in models and 'claude_code/claude-sonnet-4-6' in models
    assert 'Claude Code login' in models and 'models' in a.commands()


def test_a_saved_session_can_be_listed_and_resumed():
    a, backend = fake_agent()
    a.history = [
        {'session': 'agent_20260811-101010', 'at': 1, 'model': 'gemma-e4b',
         'prompt': 'remember cedar', 'reply': 'I will remember cedar'},
        {'session': 'agent_20260811-101010', 'at': 2, 'model': 'gemma-e4b',
         'prompt': 'what was it?', 'reply': 'cedar'}]
    assert 'remember cedar' in a.command('/sessions')
    assert '2 turns' in a.command('/resume latest')
    assert backend._resume_hist[-1] == {'role': 'assistant', 'content': 'cedar'}
    assert a.session_id == 'agent_20260811-101010'
