"""Skills and extensions: discovery, override, progressive disclosure, and the shared command surface.

One test per contract, so a failure names the behaviour that broke rather than the file it lived in.
"""
from ramabana import agent, core, tools
from ramabana.testing import fake_agent


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
    at the end. Growing one past the cap fails here rather than truncating in a briefing."""
    found = {s.name: s for s in tools.discover()}
    for name in ('coding_patterns', 'theory', 'write_prose', 'write_docs'):
        s = found[name]
        assert s.source == 'pyskill' and s.where == f'ramabana.{name}'
        assert len(s.text()) < tools.MAX_SKILL_CHARS and 'more chars]' not in s.text(), name
    assert 'Naur' in found['theory'].text()
    assert 'Banned words' in found['write_docs'].text() and 'Summaries' in found['write_docs'].text()
    assert 'Banned words' in found['write_prose'].text()
    assert 'Tests earn their place' in found['coding_patterns'].text()


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


def test_a_tool_registered_while_the_session_runs_survives_a_reload(tmp_path):
    """`reload` and `refresh` re-read the extension files, and used to discard the whole registry
    with them. Anything the process registered on it stays, and `add_tool` is the way in after
    `tools` has already been built."""
    ext = tmp_path/'extensions'; ext.mkdir()
    (ext/'wc.py').write_text('def setup(reg):\n'
                             '    @reg.tool\n'
                             '    def from_file(x: str) -> str:\n'
                             '        "A tool an extension file registered."\n'
                             '        return x\n')
    a, _ = fake_agent(cfg=tmp_path)
    a.extensions = True

    def added(x: str) -> str:
        "A tool the running process registered."
        return x

    assert 'from_file' in {t.__name__ for t in a.tools}
    before = a.tools
    a.add_tool(added)
    assert a.tools is not before                      # the built list was rebuilt around it
    assert 'added' in {t.__name__ for t in a.tools}

    for call in (a.reload, a.refresh):
        call()
        assert 'added' in {t.__name__ for t in a.tools}, call.__name__
        assert 'from_file' in {t.__name__ for t in a.tools}, call.__name__
        assert [t.__name__ for t in a.registry.tools].count('from_file') == 1, 'reloaded twice'
