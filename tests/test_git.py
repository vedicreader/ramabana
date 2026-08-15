"""The git layer: what a command is allowed to do, and what it leaves behind.

`GitGateway` is the only thing that runs `git`, so its classification, its locking and its
safepoints are contracts rather than details -- a write that takes a read lock corrupts an index,
and a mutation with no safepoint is a `reset --hard` a person cannot take back. `GitRepo`'s own
tests are about the answers it returns: a conflict is an outcome, not an exception.

This surface came from leela's `blocks/git` when the harness took ownership of it; the panels
stayed there and the porcelain moved here.
"""
import subprocess, threading, time
import pytest
from ramabana.git import GitError, GitGateway, GitRepo, classify, gateway, repo_root


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'tests@ramabana.local')
    git(tmp_path, 'config', 'user.name', 'Ramabana tests')
    (tmp_path/'app.py').write_text('value = 1\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'initial')
    return tmp_path

@pytest.fixture
def diverged(repo):
    "`main` and `feature` with one commit each, touching the same line."
    git(repo, 'checkout', '-b', 'feature')
    (repo/'app.py').write_text('value = 2\n')
    git(repo, 'commit', '-am', 'feature work')
    git(repo, 'checkout', 'main')
    (repo/'app.py').write_text('value = 3\n')
    git(repo, 'commit', '-am', 'main work')
    return repo


@pytest.mark.parametrize('args,kind', [
    (('status', '--porcelain=v1'), 'read'), (('diff', '--cached'), 'read'),
    (('branch', '--show-current'), 'read'), (('branch', '-d', 'gone'), 'write'),
    (('config', '--get', 'filter.x.clean'), 'read'), (('stash', 'list'), 'read'),
    (('tag', 'v1'), 'write'), (('merge', '--no-edit', 'feature'), 'write'),
    (('symbolic-ref', '--quiet', '--short', 'HEAD'), 'read'),
    (('symbolic-ref', 'HEAD', 'refs/heads/main'), 'write'),
    (('fetch', '--all', '--prune'), 'net'), (('push', '--set-upstream', 'origin', 'main'), 'net'),
    (('-c', 'core.hooksPath=/dev/null', 'status'), 'read'),
    (('--git-dir', '/tmp/x', 'commit', '-m', 'x'), 'write'), ((), 'write'),
])
def test_commands_are_sorted_by_what_they_do_to_the_repository(args, kind):
    assert classify(args) == kind

def test_reads_run_without_the_optional_lock_and_writes_do_not(repo, monkeypatch):
    seen = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kw: (seen.append(list(argv)), real(argv, **kw))[1])
    g = GitGateway()
    g.out(repo, 'status', '--porcelain=v1')
    g.out(repo, 'branch', 'scratch')
    assert '--no-optional-locks' in seen[0] and '--no-optional-locks' not in seen[1]

def test_a_read_shares_but_a_write_excludes_and_the_writer_may_still_read(repo):
    g, order = GitGateway(), []
    def reader():
        with g._lock(repo).read(): order.append('read'); time.sleep(.05)
    t = threading.Thread(target=reader); t.start(); time.sleep(.01)
    with g._lock(repo).write():
        order.append('write')
        g.out(repo, 'status', '--porcelain=v1')     # reentrant: the writer reads its own work
        order.append('read-inside-write')
    t.join()
    assert order == ['read', 'write', 'read-inside-write']

def test_a_safepoint_carries_uncommitted_work_and_undo_puts_it_back(repo):
    r = GitRepo.at(repo)
    (repo/'app.py').write_text('value = 99\n')
    (repo/'new.py').write_text('fresh = True\n')
    git(repo, 'add', 'new.py')
    point = gateway().safepoint(repo, 'demo')
    assert point.dirty == 2 and point.stash and point.branch == 'main'
    git(repo, 'commit', '-am', 'a commit to be undone')
    assert r.undo(point.token)['restored'] == 2
    assert (repo/'app.py').read_text() == 'value = 99\n'
    assert (repo/'new.py').exists()
    assert git(repo, 'log', '--format=%s') == 'initial'

def test_the_journal_survives_a_checkout_written_by_leela(repo):
    from ramabana.git import JOURNAL_NAME, LEELA_JOURNAL
    g = gateway()
    point = g.safepoint(repo, 'first')
    d = g._git_dir(repo)
    (d/LEELA_JOURNAL).write_text((d/JOURNAL_NAME).read_text())
    (d/JOURNAL_NAME).unlink()
    assert [p.token for p in g.journal(repo)] == [point.token]
    g.safepoint(repo, 'second')
    assert (d/JOURNAL_NAME).exists(), 'a new safepoint is written under this name, not leela\'s'
    assert [p.op for p in g.journal(repo)] == ['second', 'first']

def test_a_conflicted_merge_is_an_outcome_rather_than_an_exception(diverged):
    r = GitRepo.at(diverged)
    out = r.merge('feature')
    assert out['conflicted'] == ['app.py'] and out['operation']['active'] == 'merge'
    assert 'conflicted' in out['summary'] and out['undo']
    plan = r.conflict_plan()
    assert plan['summary'] == {'files': 1, 'blocks': 1, 'safe': 0, 'manual': 1}
    versions = r.conflict_versions('app.py')
    assert versions['ours'] == 'value = 3\n' and versions['theirs'] == 'value = 2\n'
    assert r.resolve_conflict('app.py', 'theirs')['conflicted'] == []
    assert (diverged/'app.py').read_text() == 'value = 2\n'

def test_a_dirty_tree_no_longer_refuses_a_merge_and_the_work_comes_back(repo):
    "The complaint that started this: refuse where other tools shelve, do it, and restore."
    git(repo, 'checkout', '-b', 'feature')
    (repo/'lib.py').write_text('shared = True\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-m', 'feature work')
    git(repo, 'checkout', 'main')
    r = GitRepo.at(repo)
    (repo/'app.py').write_text('value = 42\n')
    out = r.merge('feature')
    assert (repo/'lib.py').exists(), 'the merge happened'
    assert (repo/'app.py').read_text() == 'value = 42\n', 'the uncommitted edit came back'
    assert out['kept_work'] and not out['note']
    assert git(repo, 'stash', 'list') == '', 'nothing was left on the stash stack'

def test_a_preview_names_the_relation_and_rehearses_the_conflict(diverged):
    r = GitRepo.at(diverged)
    merge = r.merge_preview('feature')
    assert merge['relation'] == 'diverged' and merge['conflict_likely']
    assert merge['conflicts'] == ['app.py'] and merge['clean']
    rebase = r.rebase_preview('feature')
    assert [c['subject'] for c in rebase['commits']] == ['main work']
    assert not rebase['already_based'] and rebase['conflict_likely']

def test_an_operation_can_be_continued_or_abandoned_by_name(diverged):
    r = GitRepo.at(diverged)
    r.merge('feature')
    with pytest.raises(GitError): r.operation_action('skip')      # a merge has nothing to skip
    assert r.operation_action('abort')['operation']['active'] == ''
    assert (diverged/'app.py').read_text() == 'value = 3\n'

def test_status_reports_the_drift_a_person_asks_about(repo, tmp_path):
    upstream = tmp_path.parent/'origin.git'
    git(repo, 'clone', '--bare', str(repo), str(upstream))
    git(repo, 'remote', 'add', 'origin', str(upstream))
    git(repo, 'fetch', '-q', 'origin')
    git(repo, 'branch', '--set-upstream-to=origin/main', 'main')
    (repo/'app.py').write_text('value = 2\n')
    git(repo, 'commit', '-am', 'local work')
    info = GitRepo.at(repo).info()
    assert info['ahead'] == 1 and info['behind'] == 0 and info['upstream'] == 'origin/main'
    assert info['clean'] and info['branch'] == 'main'

def test_a_path_outside_any_repository_has_no_root(tmp_path):
    assert repo_root(tmp_path/'nowhere') is None
    with pytest.raises(GitError): GitRepo.at(tmp_path/'nowhere')

def test_the_gateway_inherits_this_environment_until_a_host_says_otherwise(repo):
    g = GitGateway()
    assert g.env(repo) is None
    g.env_for = lambda cwd: {'PATH': '/nowhere'}
    assert g.env(repo) == {'PATH': '/nowhere'}
    g.env_for = lambda cwd: (_ for _ in ()).throw(RuntimeError('no venv here'))
    g._env_cache.clear()
    assert g.env(repo) is None, 'a host that cannot answer must not break git'
