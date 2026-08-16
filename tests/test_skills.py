"""Skills and extensions: discovery, override, progressive disclosure, and the shared command surface.

One test per contract, so a failure names the behaviour that broke rather than the file it lived in.
"""
import pytest

from ramabana import agent, core, tools
from ramabana.testing import fake_agent
from ramabana.tools import Registry, Skill, find, load


def test_skills_are_discovered_from_packages_and_overridden_by_files(tmp_path):
    "Installed pyskills appear, a project's own `SKILL.md` wins, and a loose `.md` is not a skill."
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


def test_every_ramabana_pyskill_reaches_the_agent_whole():
    """`Skill.text` clips at `MAX_SKILL_CHARS`, and a writing skill clipped mid-list loses the tells
    at the end of it. The ones this package ships have to fit, so growing one past the cap fails here
    rather than silently truncating in a briefing."""
    found = {s.name: s for s in tools.discover()}
    for name in ('coding_patterns', 'theory', 'write_prose', 'write_docs'):
        s = found[name]
        assert s.source == 'pyskill' and s.where == f'ramabana.{name}'
        assert len(s.text()) < tools.MAX_SKILL_CHARS, f'{name} is clipped'
        assert 'more chars]' not in s.text()
    assert 'Naur' in found['theory'].text()
    assert 'Banned words' in found['write_docs'].text() and 'Summaries' in found['write_docs'].text()
    assert 'Banned words' in found['write_prose'].text()
    assert 'Tests earn their place' in found['coding_patterns'].text()


def test_the_index_carries_names_not_bodies_and_find_refuses_to_guess():
    "Progressive disclosure: one clipped line per skill, never a body, and no guessing on a prefix."
    ss = tools.discover()
    idx = tools.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert len(rows) == len(ss)
    for r in rows: assert len(r) <= tools.SKILL_DESC_MAX + max(len(s.name) for s in ss) + 8
    two = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(two, 'edit') is None and find(two, 'editskill').name == 'editskill'


def test_an_extension_adds_a_tool_a_skill_and_a_command_and_never_crashes_the_session(tmp_path):
    "Project extensions are off unless asked for, and everything they get wrong is reported, not raised."
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
    assert 'mine.py: 1 tool(s), 1 skill(s), 1 command(s)' in reg.notes

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
