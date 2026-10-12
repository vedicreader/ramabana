"A host gives each job its own git worktree, opened as a root."
import subprocess

from ramabana.agent import mk_host


def git(*a, cwd): return subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

def test_a_job_gets_a_worktree_on_its_own_branch_opened_as_a_root(tmp_path):
    repo = tmp_path/'vedicreader'; repo.mkdir()
    git('init', '-q', '-b', 'main', cwd=repo)
    (repo/'a.py').write_text('x = 1\n')
    git('add', '.', cwd=repo); git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'start', cwd=repo)
    host = mk_host([str(repo)], web=False, index=False)
    wt = host.add_worktree(repo, 'adapt-isha')
    assert (wt/'a.py').exists() and git('branch', '--show-current', cwd=wt) == 'adapt-isha'
    assert str(wt.resolve()) in host.roots, 'opened for the job to write'
    ro = host.add_worktree(repo, 'main-view', readonly=True)
    assert str(ro.resolve()) in host.read_roots and str(ro.resolve()) not in host.roots
    git('branch', 'ready', cwd=repo)
    reused = host.add_worktree(repo, 'ready')
    assert git('branch', '--show-current', cwd=reused) == 'ready', 'a branch that exists is checked out, not made'
    try: host.add_worktree(repo, 'adapt-isha', path=tmp_path/'second')
    except RuntimeError as e: assert 'adapt-isha' in str(e)
    else: raise AssertionError('a branch checked out in another worktree is refused')
