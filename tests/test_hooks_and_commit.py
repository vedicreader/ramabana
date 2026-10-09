"""Background answers reach the next turn, hooks can deny or rewrite, and `/commit` drafts then commits."""
import subprocess

from ramabana.agent import Approvals
from ramabana.tools import ERR
from ramabana.testing import fake_agent


def test_a_rewritten_write_goes_back_through_approvals():
    hook = lambda ag, name, args: {'path': '/proj/c.py', 'text': args['text']} if name == 'create_file' else None
    for mode, ok in (('auto', True), ('off', False)):
        a, _ = fake_agent(approvals=Approvals(tools={'create_file'}, mode=mode))
        a.registry.on('before_tool', hook)
        out = {t.__name__: t for t in a.tools}['create_file']('/proj/b.py', 'x = 1\n')
        assert (a.host.read('/proj/c.py') == 'x = 1\n') is ok and out.startswith(ERR) is not ok, (mode, out)


def _git(cwd, *args): return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


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
