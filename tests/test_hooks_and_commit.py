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


def test_a_git_write_leaves_an_undo_token_that_rewind_applies_and_run_shell_refuses_the_same_write(tmp_path):
    from shalya.host import LocalHost
    from ramabana.tools import failed
    repo, cfg = tmp_path/'repo', tmp_path/'cfg'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main'); _git(repo, 'config', 'user.email', 't@t'); _git(repo, 'config', 'user.name', 't')
    (repo/'a.txt').write_text('hi\n'); _git(repo, 'add', 'a.txt'); _git(repo, 'commit', '-q', '-m', 'init')
    _git(repo, 'checkout', '-q', '-b', 'other'); (repo/'a.txt').write_text('other\n'); _git(repo, 'commit', '-q', '-am', 'on other'); _git(repo, 'checkout', '-q', 'main')
    a, _ = fake_agent(host=LocalHost([str(repo)], index=False), cfg=cfg)
    tools = {t.__name__: t for t in a.tools}
    out = tools['run_shell']('git commit -m x')
    assert failed(out) and '`git_commit`' in out and a.activity.rows()[-1]['ok'] is False
    assert not failed(tools['run_shell']('git status')), 'a read runs'
    before_count = _git(repo, 'log', '--oneline').count('\n')
    a._prepare('commit the change')
    (repo/'a.txt').write_text('hello\n')
    a.command('/commit fix')                                   # still binds git_commit(msg, paths)
    kept = a.git_undo[a.current_turn_id]
    assert kept[0]['tool'] == 'git_commit' and kept[0]['undo'] and kept[0]['head']
    assert (a.checkpoint_dir/f'{a.current_turn_id}.git.json').exists()
    tools['git_checkout']('other')                              # a git write is snapshotted: the checkout moved a file
    assert '/a.txt' in ''.join(a.changes()) and len(a.git_undo[a.current_turn_id]) == 2
    a._finish('done')
    said = a.command('/rewind files')
    assert 'undid 2 git write' in said, said
    assert _git(repo, 'log', '--oneline').count('\n') == before_count and _git(repo, 'branch', '--show-current') == 'main'
    assert (repo/'a.txt').read_text() == 'hello\n', 'the uncommitted edit is kept, not lost'




def test_rewind_undoes_git_writes_from_memory_when_no_checkpoint_was_written():
    "No config dir means no `<turn>.git.json`; the turn's tokens are still held on the agent."
    a, _ = fake_agent()
    a._prepare('push it')
    a.git_undo[a.current_turn_id] = [{'tool': 'git_remote', 'summary': 'pushed main', 'undo': '', 'undoes': '', 'head': ''}]
    a._finish('done')
    said = a.command('/rewind files')
    assert '1 git write(s) this turn cannot be undone here: git_remote' in said and 'no file checkpoint' not in said


def test_run_shell_is_only_steered_to_a_git_tool_this_agent_has():
    "The guard names a tool; on a host without the git group there is none to name, so the command goes to approvals like any other."
    from ramabana.tools import failed
    a, _ = fake_agent()                                       # MemHost: no git group
    tools = {t.__name__: t for t in a.tools}
    assert 'git_commit' not in tools
    assert not a._deny_git_shell('run_shell', {'command': 'git commit -m x'})
    out = tools['run_shell']('git commit -m x')
    assert not (failed(out) and '`git_commit`' in out), out
