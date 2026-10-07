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




def _repo_with_a_commit(tmp_path):
    repo = tmp_path/'repo'; repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main'); _git(repo, 'config', 'user.email', 't@t'); _git(repo, 'config', 'user.name', 't')
    (repo/'a.txt').write_text('hi\n'); _git(repo, 'add', 'a.txt'); _git(repo, 'commit', '-q', '-m', 'init')
    return repo


def test_rewind_refuses_the_git_undo_once_head_has_moved_and_keeps_the_later_commit(tmp_path):
    """gheasy's undo is a `reset --hard` to the pre-write head. A commit made after the turn would go with it, so
    the rewind checks HEAD first and, when it moved, touches neither git nor files."""
    from shalya.host import LocalHost
    repo = _repo_with_a_commit(tmp_path)
    a, _ = fake_agent(host=LocalHost([str(repo)], index=False), cfg=tmp_path/'cfg', approvals=Approvals(tools=set(), mode='auto'))
    tools = {t.__name__: t for t in a.tools}
    a._prepare('commit the change')
    tools['replace_text']('a.txt', [{'oldText': 'hi', 'newText': 'hello'}])
    tools['git_commit']('turn commit', 'a.txt')
    a._finish('done')
    turn_head = _git(repo, 'rev-parse', 'HEAD')
    (repo/'b.txt').write_text('mine\n'); _git(repo, 'add', 'b.txt'); _git(repo, 'commit', '-q', '-m', 'user commit after the turn')
    said = a.command('/rewind files')
    assert 'HEAD moved after the turn' in said and 'git undo refused' in said and 'undid' not in said and 'restored' not in said, said
    assert _git(repo, 'rev-parse', 'HEAD') != turn_head and _git(repo, 'log', '--oneline').count('\n') == 2, 'the later commit is intact'
    assert (repo/'a.txt').read_text() == 'hello\n' and (repo/'b.txt').exists(), 'files untouched: they would diverge from git otherwise'
    assert not any(x.tool == 'rewind' for x in a.approvals.history), 'refused before anybody was asked'
    _git(repo, 'reset', '-q', '--hard', 'HEAD~1')                   # the person takes the later commit back
    said = a.command('/rewind files')
    assert 'undid 1 git write' in said and 'restored 1 file' in said, said
    assert _git(repo, 'log', '--oneline').count('\n') == 0 and (repo/'a.txt').read_text() == 'hi\n'
    ask = next(x for x in a.approvals.history if x.tool == 'rewind')
    assert ask.args['git'] and ask.args['git'][0].startswith('git_commit: ') and 'undoes' in ask.args['git'][0], ask.args


def test_rewind_refuses_the_git_undo_when_the_branch_changed_after_the_turn(tmp_path):
    from shalya.host import LocalHost
    repo = _repo_with_a_commit(tmp_path)
    a, _ = fake_agent(host=LocalHost([str(repo)], index=False), cfg=tmp_path/'cfg')
    tools = {t.__name__: t for t in a.tools}
    a._prepare('commit'); (repo/'a.txt').write_text('hello\n'); tools['git_commit']('turn commit', 'a.txt'); a._finish('done')
    _git(repo, 'checkout', '-q', '-b', 'feature')
    said = a.command('/rewind files')
    assert 'branch changed after the turn (main -> feature)' in said and 'git undo refused' in said, said
    assert _git(repo, 'branch', '--show-current') == 'feature' and _git(repo, 'log', '--oneline').count('\n') == 1


def _turn_that_commits(tmp_path, **kw):
    "A repo with one commit, and an agent that spent a turn editing and committing `a.txt` in it."
    from shalya.host import LocalHost
    repo = _repo_with_a_commit(tmp_path)
    (repo/'b.txt').write_text('theirs\n'); _git(repo, 'add', 'b.txt'); _git(repo, 'commit', '-q', '-m', 'b')
    a, _ = fake_agent(host=LocalHost([str(repo)], index=False), cfg=tmp_path/'cfg', approvals=Approvals(tools=set(), mode='auto'), **kw)
    tools = {t.__name__: t for t in a.tools}
    a._prepare('commit the change'); tools['replace_text']('a.txt', [{'oldText': 'hi', 'newText': 'hello'}]); tools['git_commit']('turn commit', 'a.txt'); a._finish('done')
    return repo, a


def test_rewind_refuses_the_git_undo_over_uncommitted_edits_to_other_files(tmp_path):
    """HEAD still where the turn left it, but the person has edited `b.txt` since and not committed: gheasy's
    `reset --hard` would take that edit with it, so the rewind refuses and touches neither git nor files."""
    repo, a = _turn_that_commits(tmp_path)
    (repo/'b.txt').write_text('mine, uncommitted\n')
    said = a.command('/rewind files')
    assert 'uncommitted changes to b.txt after the turn' in said and 'git undo refused' in said and 'undid' not in said and 'restored' not in said, said
    assert (repo/'b.txt').read_text() == 'mine, uncommitted\n', 'the edit is intact'
    assert (repo/'a.txt').read_text() == 'hello\n' and _git(repo, 'log', '--oneline').count('\n') == 2, 'nothing was touched'
    assert not any(x.tool == 'rewind' for x in a.approvals.history), 'refused before anybody was asked'
    _git(repo, 'stash', '-q')                                       # the person sets the edit aside
    said = a.command('/rewind files')
    assert 'undid 1 git write' in said and 'restored 1 file' in said, said
    assert (repo/'a.txt').read_text() == 'hi\n' and _git(repo, 'log', '--oneline').count('\n') == 1


def test_rewind_proceeds_when_the_only_dirty_file_is_one_the_turn_wrote(tmp_path):
    "A later edit to a file the turn checkpointed is what the rewind puts back anyway, so it is no reason to refuse."
    repo, a = _turn_that_commits(tmp_path)
    (repo/'a.txt').write_text('hello again\n')
    said = a.command('/rewind files')
    assert 'undid 1 git write' in said and 'restored 1 file' in said and 'refused' not in said, said
    assert (repo/'a.txt').read_text() == 'hi\n' and (repo/'b.txt').read_text() == 'theirs\n' and _git(repo, 'log', '--oneline').count('\n') == 1


def test_rewind_refuses_the_git_undo_when_head_cannot_be_read(tmp_path):
    "A guard that cannot see HEAD fails closed: no reset against an unknown tree."
    repo, a = _turn_that_commits(tmp_path)
    (repo/'.git'/'HEAD').write_text('garbage\n')
    said = a.command('/rewind files')
    assert 'cannot read HEAD' in said and 'git undo refused' in said and 'undid' not in said and 'restored' not in said, said
    assert (repo/'a.txt').read_text() == 'hello\n'


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


def _two_repos(tmp_path):
    "Two repositories, each its own open folder, the second one not the first root."
    first, second = _repo_with_a_commit(tmp_path), tmp_path/'second'
    second.mkdir()
    _git(second, 'init', '-q', '-b', 'main'); _git(second, 'config', 'user.email', 't@t'); _git(second, 'config', 'user.name', 't')
    (second/'c.txt').write_text('one\n'); _git(second, 'add', 'c.txt'); _git(second, 'commit', '-q', '-m', 'init')
    return first, second


def test_rewind_undoes_a_commit_made_in_a_second_repository(tmp_path):
    "The undo token keeps the repository it came from, so `/rewind` checks and resets that one, not the first root."
    from shalya.host import LocalHost
    first, second = _two_repos(tmp_path)
    a, _ = fake_agent(host=LocalHost([str(first), str(second)], index=False), cfg=tmp_path/'cfg', approvals=Approvals(tools=set(), mode='auto'))
    tools = {t.__name__: t for t in a.tools}
    first_head = _git(first, 'rev-parse', 'HEAD')
    a._prepare('commit in the second repository')
    tools['replace_text'](str(second/'c.txt'), [{'oldText': 'one', 'newText': 'two'}])
    tools['git_commit']('turn commit', 'c.txt', path=str(second))
    a._finish('done')
    assert _git(second, 'log', '-1', '--format=%s') == 'turn commit'
    assert a.git_undo[a.current_turn_id][0]['root'] == str(second.resolve())
    said = a.command('/rewind files')
    assert 'undid 1 git write' in said and 'restored 1 file' in said and 'refused' not in said, said
    assert _git(second, 'log', '--oneline').count('\n') == 0 and (second/'c.txt').read_text() == 'one\n'
    assert _git(first, 'rev-parse', 'HEAD') == first_head


def test_a_git_write_with_a_path_snapshots_the_tree_and_records_nothing_as_binary(tmp_path):
    "A git tool's `path` names the repository, not a file: the call snapshots the tree, and the folder never lands in `binary`."
    from shalya.host import LocalHost
    from ramabana.tools import write_targets
    first, second = _two_repos(tmp_path)
    assert write_targets('git_checkout', {'branch': 'x', 'path': str(second)}) == []
    _git(second, 'checkout', '-q', '-b', 'other'); (second/'c.txt').write_text('other\n'); _git(second, 'commit', '-q', '-am', 'on other'); _git(second, 'checkout', '-q', 'main')
    a, _ = fake_agent(host=LocalHost([str(first), str(second)], index=False), cfg=tmp_path/'cfg', approvals=Approvals(tools=set(), mode='auto'))
    tools = {t.__name__: t for t in a.tools}
    a._prepare('switch branches in the second repository')
    tools['git_checkout']('other', path=str(second))
    assert not a.binary and str(second) not in a.before, (a.binary, a.before)
    assert any(p.endswith('c.txt') for p in a.changes()), 'the checkout moved a file and the snapshot saw it'


def test_commit_takes_a_repository_path_and_names_it_in_the_approval(tmp_path):
    "`/commit PATH MESSAGE` commits in the repository holding PATH; the approval preview names its root."
    from shalya.host import LocalHost
    first, second = _two_repos(tmp_path)
    a, _ = fake_agent(host=LocalHost([str(first), str(second)], index=False), approvals=Approvals(tools=set(), mode='auto'))
    a.approvals.host = a.host                                 # as `make_agent` wires it
    (second/'c.txt').write_text('changed\n')
    assert 'ERROR' not in a.command(f'/commit {second} Change c')
    assert _git(second, 'log', '-1', '--format=%s') == 'Change c' and not _git(second, 'status', '--porcelain')
    assert _git(first, 'log', '--oneline').count('\n') == 0
    ask = next(x for x in a.approvals.history if x.tool == 'git_commit')
    assert ask.preview.startswith(f'in {second.resolve()}'), ask.preview
    assert a.command(f'/commit {second}') == 'nothing to commit'
