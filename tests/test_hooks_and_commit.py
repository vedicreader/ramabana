"""Background answers reach the next turn, hooks can deny or rewrite, and `/commit` drafts then commits."""
import subprocess

from ramabana.agent import Approvals
from ramabana.runtime import Run
from ramabana.tools import ERR
from ramabana.testing import fake_agent

from test_background import until


def test_a_finished_background_delegation_reaches_the_next_turn_unasked():
    a, _ = fake_agent(replies=['ok', 'ok'])
    a.background.start(lambda r: 'x is 42', Run('run_x', 'background', 'what is x', 'fake'))
    assert until(lambda: a.background.result('run_x') == 'x is 42')
    out = a._prepare('next')
    assert '<background-results>' in out and 'x is 42' in out and 'what is x' in out
    assert '<background-results>' not in a._prepare('again'), 'a notice is delivered once'
    assert a.background.result('run_x') == 'x is 42', 'and `delegate_result` still answers'


def test_hooks_can_deny_a_call_rewrite_its_arguments_and_replace_its_result():
    a, _ = fake_agent()
    a.registry.on('before_tool', lambda ag, name, args: 'denied by hook' if str(args.get('path', '')).endswith('secret') else None)
    a.registry.on('before_tool', lambda ag, name, args: {'path': '/proj/a.py'} if args.get('path') == '/proj/b.py' else None)
    a.registry.on('after_tool', lambda ag, name, out: out.upper() if name == 'list_files' else None)
    tools = {t.__name__: t for t in a.tools}
    assert tools['view_file']('/proj/secret').startswith(ERR) and 'denied by hook' in tools['view_file']('/proj/secret')
    assert 'def a' in tools['view_file']('/proj/b.py')
    assert 'A.PY' in tools['list_files']()


def test_a_rewritten_write_goes_back_through_approvals():
    hook = lambda ag, name, args: {'path': '/proj/c.py', 'text': args['text']} if name == 'create_file' else None
    for mode, ok in (('auto', True), ('off', False)):
        a, _ = fake_agent(approvals=Approvals(tools={'create_file'}, mode=mode))
        a.registry.on('before_tool', hook)
        out = {t.__name__: t for t in a.tools}['create_file']('/proj/b.py', 'x = 1\n')
        assert (a.host.read('/proj/c.py') == 'x = 1\n') is ok and out.startswith(ERR) is not ok, (mode, out)


def _git(cwd, *args): return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_commit_drafts_from_the_diff_and_commits_through_the_tools(tmp_path):
    from shalya.host import LocalHost
    _git(tmp_path, 'init', '-q'); _git(tmp_path, 'config', 'user.email', 't@t'); _git(tmp_path, 'config', 'user.name', 't')
    (tmp_path/'a.txt').write_text('hi\n'); _git(tmp_path, 'add', 'a.txt'); _git(tmp_path, 'commit', '-q', '-m', 'init')
    a, _ = fake_agent(host=LocalHost([str(tmp_path)], index=False))
    assert a.command('/commit') == 'nothing to commit'
    (tmp_path/'a.txt').write_text('hello\n')
    assert 'ERROR' not in a.command('/commit Say hello')
    assert _git(tmp_path, 'log', '-1', '--format=%s') == 'Say hello' and not _git(tmp_path, 'status', '--porcelain')
    (tmp_path/'a.txt').write_text('hey\n'); _git(tmp_path, 'add', 'a.txt')
    a.command('/commit')
    assert _git(tmp_path, 'log', '-1', '--format=%s').startswith('ONESHOT:'), 'no message given: the one-shot model drafts it from the staged diff'
    assert 'commit' in a.commands() and 'pr' in a.commands()
