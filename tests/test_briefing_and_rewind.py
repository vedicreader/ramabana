"""Instruction files, edit previews, saved approval rules, the verify gate, file rewind and file memory."""
import json

from ramabana.agent import Approvals, CLAUDE_NOTES, preview_for
from ramabana.testing import MemHost, fake_agent
from ramabana.tools import WRITE_TOOLS

PY = '[tool.ramabana]\nverify = "pytest -q"\n'


def test_claude_md_and_the_users_agents_md_reach_the_briefing(tmp_path):
    (tmp_path/'AGENTS.md').write_text('USER RULE')
    a, _ = fake_agent(MemHost({'/proj/CLAUDE.md': 'PROJECT RULE'}), cfg=tmp_path)
    sp = a.system_prompt()
    assert sp.index('USER RULE') < sp.index('PROJECT RULE')
    assert CLAUDE_NOTES not in sp
    a.spec_or_none = lambda job='turn': type('S', (), {'runtime': 'claude', 'model_id': 'opus'})()
    assert CLAUDE_NOTES in a.system_prompt()


def test_a_replace_text_preview_is_a_diff_and_a_shell_preview_is_the_command():
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    edits = [{'oldText': 'pass', 'newText': 'return 1'}]
    diff = preview_for('replace_text', {'path': '/proj/a.py', 'edits': edits}, host)
    assert '-def a(): pass' in diff and '+def a(): return 1' in diff
    assert 'no edits given' in preview_for('replace_text', {'path': '/proj/a.py', 'edits': []}, host)
    assert 'no edits given' in preview_for('edit_cell', {'path': '/proj/n.ipynb', 'cell_id': 'c1', 'edits': []})
    shell = preview_for('run_shell', {'command': 'pytest -q', 'cwd': '/proj'}, host)
    assert 'pytest -q' in shell and '/proj' in shell and '{' not in shell


def test_saved_rules_decide_without_asking_and_survive_a_restart(tmp_path):
    ap = Approvals(tools={'run_shell', 'edit_file'}, rules_path=tmp_path/'approvals.json')
    ap.always('run_shell', 'pytest*', glob=True)
    ap.always('run_shell', 'rm *', 'deny', glob=True)
    assert ap.request('run_shell', {'command': 'pytest -q'}).answer is True
    denied = ap.request('run_shell', {'command': 'rm -rf build'})
    assert denied.answer is False and 'rule' in denied.note
    assert 'listening' in ap.request('run_shell', {'command': 'ls'}).note
    assert Approvals(tools={'run_shell'}, rules_path=tmp_path/'approvals.json').rules == ap.rules
    edits = Approvals(tools=WRITE_TOOLS, mode='edits')
    assert edits.request('edit_file', {'path': 'a.py'}).answer is True
    assert edits.request('run_shell', {'command': 'ls'}).answer is False


def _turn_that_wrote(a, host):
    a._prepare('change a')
    a.before['/proj/a.py'] = host.files['/proj/a.py']
    host.files['/proj/a.py'] = 'def a(): return 1\nprint(a())\n'


def test_a_turn_that_wrote_without_checking_runs_the_project_check():
    host = MemHost({'/proj/a.py': 'def a(): pass\n', '/proj/pyproject.toml': PY}, commands={'pytest -q': (0, '3 passed')})
    a, _ = fake_agent(host)
    _turn_that_wrote(a, host)
    assert 'a.py' in a.changed_line() and '+2 -1' in a.changed_line()
    out = a._finish('done')
    assert 'verify (pytest -q)' in out and '3 passed' in out and host.cmds[0][0] == 'pytest -q'
    assert a._finish('nothing changed') == 'nothing changed'


def test_rewind_restores_the_files_a_turn_changed(tmp_path):
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    _turn_that_wrote(a, host)
    a._finish('done')
    assert list((tmp_path/'checkpoints'/a.session_id).glob('*.json'))
    assert f'restored 1 file(s) to before {a.current_turn_id}' in a.command('/rewind files')
    assert host.files['/proj/a.py'] == 'def a(): pass\n'
    assert 'no file checkpoint' in a.command('/rewind nosuchturn files')
    assert '* main' in a.command('/branches')


def test_notes_survive_without_a_vault_and_reach_the_briefing(tmp_path):
    from ramabana.tools import is_write
    a, _ = fake_agent(cfg=tmp_path)
    names = {t.__name__: t for t in a.tools}
    assert 'remember' in names and 'remember_note' not in names and not is_write(names['remember'])
    assert 'remembered' in names['remember']('use uv, never pip', key='pkg')
    assert 'replaced' in names['remember']('use uv (uv add for deps)', key='pkg')
    names['remember']('tests run with nbdev-test', title='Tests', tags='ci')
    b, _ = fake_agent(cfg=tmp_path)
    sp = b.system_prompt()
    assert '- [pkg] use uv (uv add for deps)' in sp and 'never pip' not in sp and '- **Tests**: tests run with nbdev-test' in sp
    assert fake_agent()[0].note_memory('x').startswith('no config')


def test_rewind_removes_the_files_a_turn_created_and_restores_the_ones_it_changed(tmp_path):
    "A file that did not exist before the turn is deleted, not left as an empty file; a second write to it is the same change."
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    tools = {t.__name__: t for t in a.tools}
    a._prepare('add b')
    tools['create_file']('/proj/b.py', 'x = 1\n')
    tools['create_file']('/proj/a.py', 'def a(): return 1\n')
    tools['create_file']('/proj/b.py', 'x = 2\n')
    assert a.new == {'/proj/b.py'}
    a._finish('done')
    said = a.command('/rewind files')
    assert f'restored 1 file(s) to before {a.current_turn_id}' in said and 'removed 1 file(s) created that turn' in said, said
    assert host.files == {'/proj/a.py': 'def a(): pass\n'}


def test_a_checkpoint_of_bare_texts_from_before_still_restores(tmp_path):
    import json
    host = MemHost({'/proj/a.py': 'changed\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    a._prepare('x'); a._finish('done')
    d = a.checkpoint_dir; d.mkdir(parents=True, exist_ok=True)
    (d/f'{a.current_turn_id}.json').write_text(json.dumps({'/proj/a.py': 'orig\n'}))
    assert 'restored 1 file(s)' in a.command('/rewind files') and host.files['/proj/a.py'] == 'orig\n'


def test_a_host_deletes_only_inside_its_roots():
    import pytest
    from shalya.core import HostError
    from ramabana.testing import FullHost
    from ramabana.tools import NullHost
    h = FullHost(files={'a.py': 'x'})
    h.delete('a.py'); h.delete('a.py')                       # gone, and gone again is not an error
    assert not (h.root/'a.py').exists()
    with pytest.raises(HostError): h.delete('/etc/hosts')
    with pytest.raises(HostError): NullHost().delete('a.py')
