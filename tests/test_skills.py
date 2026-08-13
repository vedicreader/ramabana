"""Skills and extensions: discovery, override, briefing disclosure, and the shared command surface."""
import pytest

from ramabana import agent, core, tools
from ramabana.testing import fake_agent
from ramabana.tools import Registry, Skill, find, load


def test_skills_discover_override_index_and_extensions(tmp_path):
    "Installed pyskills appear; file SKILL.md wins; index carries names not bodies; extensions add tools/skills/commands without crashing."
    found = {s.name: s for s in tools.discover()}
    assert 'exhash' in found and found['exhash'].source == 'pyskill' and found['exhash'].text().strip()
    patterns = found['coding_patterns']
    assert patterns.source == 'pyskill' and patterns.where == 'ramabana.coding_patterns'
    assert 'Every construct must earn its place' in patterns.text()
    assert 'Ramabana workflow' in patterns.text()

    d = tmp_path/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: ours\n---\n\nlocal body\n')
    (tmp_path/'skills'/'loose.md').write_text('not a skill')
    over = {s.name: s for s in tools.discover(cfg=tmp_path)}
    assert over['exhash'].source == 'md' and over['exhash'].description == 'ours'
    assert 'local body' in over['exhash'].text() and 'loose' not in over

    meta, body = tools.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'

    ss = tools.discover()
    idx = tools.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert len(rows) == len(ss)
    for r in rows: assert len(r) <= tools.SKILL_DESC_MAX + max(len(s.name) for s in ss) + 8
    two = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(two, 'edit') is None and find(two, 'editskill').name == 'editskill'

    ext = tmp_path/'extensions'
    ext.mkdir(parents=True)
    (ext/'mine.py').write_text(
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

    (ext/'mine.py').unlink()
    (ext/'bad.py').write_text('raise RuntimeError("boom")\n')
    broken = load(Registry(), cfg=tmp_path)
    assert broken.tools == [] and any('boom' in n for n in broken.notes)

    proj = tmp_path/'.leela'/'extensions'
    proj.mkdir(parents=True)
    (proj/'x.py').write_text('def setup(ext):\n    ext.command("boom", lambda a, b: "", "")\n')
    assert load(Registry(), roots=[tmp_path]).commands == {}
    assert 'boom' in load(Registry(), roots=[tmp_path], project=True).commands
    with pytest.raises(KeyError): Registry().on('after_lunch', lambda: None)


def test_shared_commands_and_session_resume(monkeypatch):
    "CLI and MCP share one command table; sessions list and resume restore history."
    a, backend = fake_agent()
    assert {'model', 'cost', 'compact', 'skills', 'tools', 'reload'} <= set(a.commands())
    assert a.command('nonsense') is None and a.command('cost') is not None
    out = a.command('model')
    for job in core.JOBS: assert job in out, job

    monkeypatch.setattr(agent, 'available_models', lambda include_legacy=False: [
        {'value': 'gemma-e4b', 'provider': 'litert', 'source': 'on device'},
        {'value': 'claude_code/claude-sonnet-4-6', 'provider': 'claude_code',
         'source': 'Claude Code login'}])
    models = a.command('/models')
    assert 'gemma-e4b' in models and 'claude_code/claude-sonnet-4-6' in models
    assert 'Claude Code login' in models and 'models' in a.commands()

    a.history = [
        {'session': 'agent_20260811-101010', 'at': 1, 'model': 'gemma-e4b',
         'prompt': 'remember cedar', 'reply': 'I will remember cedar'},
        {'session': 'agent_20260811-101010', 'at': 2, 'model': 'gemma-e4b',
         'prompt': 'what was it?', 'reply': 'cedar'}]
    assert 'remember cedar' in a.command('/sessions')
    assert '2 turns' in a.command('/resume latest')
    assert backend._resume_hist[-1] == {'role': 'assistant', 'content': 'cedar'}
    assert a.session_id == 'agent_20260811-101010'
