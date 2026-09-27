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


def test_what_a_poll_fired_reaches_the_next_prompt_once():
    """`poll_watches` runs at the top of a turn in a thread; what it fired used to reach only the host's
    note stream, so the model never knew a reminder had come due until it searched memory by luck."""
    from ramabana.testing import MemHost
    class Polls(MemHost):
        def poll(self): return dict(checked=5, ran=2, results=[dict(id='w3', kind='url', target='https://x.test', status='ok'),
                                                                dict(id='w7', action='remind', target='renew domain', status='ok')],
                                    housekeeping=dict(stale=1, pruned=0))
    a, _ = fake_agent(Polls({'/proj/a.py': 'x\n'}), replies=['ok', 'ok'])
    a.poll_watches(force=True).join()
    out = a._prepare('next')
    assert '<watch-results>' in out and '2 of 5 watches fired' in out and '- w3 url https://x.test: ok' in out
    assert '- w7 remind renew domain: ok' in out and 'housekeeping: 1 stale, 0 pruned' in out and 'memory_search' in out
    assert '<watch-results>' not in a._prepare('again'), 'a notice is delivered once'
    quiet, _ = fake_agent()
    t = quiet.poll_watches(force=True); t and t.join()
    assert quiet.watch_notice() == ''                       # MemHost.poll raises NotImplementedError: nothing to say
    class Idle(MemHost):
        def poll(self): return dict(checked=3, ran=0, results=[], housekeeping=dict(stale=0, pruned=0))
    idle, _ = fake_agent(Idle({'/proj/a.py': 'x\n'}))
    idle.poll_watches(force=True).join()
    assert idle.watch_notice() == ''                        # a poll that found nothing produces no notice


def test_hooks_can_deny_a_call_rewrite_its_arguments_and_replace_its_result():
    a, _ = fake_agent()
    a.registry.on('before_tool', lambda ag, name, args: 'denied by hook' if str(args.get('path', '')).endswith('secret') else None)
    a.registry.on('before_tool', lambda ag, name, args: {'path': '/proj/a.py'} if args.get('path') == '/proj/b.py' else None)
    a.registry.on('after_tool', lambda ag, name, out: out.upper() if name == 'ls' else None)
    tools = {t.__name__: t for t in a.tools}
    assert tools['view_file']('/proj/secret').startswith(ERR) and 'denied by hook' in tools['view_file']('/proj/secret')
    assert 'def a' in tools['view_file']('/proj/b.py')
    assert 'A.PY' in tools['ls'](recursive=True)   # `MemHost` has no disk: the recursive listing walks the host


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
