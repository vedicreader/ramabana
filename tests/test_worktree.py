"""Worktree-isolated delegation: a real git worktree and branch a sub-agent writes in without
touching the parent's own tree, and the background run that drives it.
"""
import subprocess
import time

from ramabana.agent import Agent
from ramabana.testing import fake_agent
from ramabana.vault import WorkspaceHost


def until(f, secs=5):
    "Wait for `f()` to be truthy, and return whether it became so."
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if f(): return True
        time.sleep(.01)
    return bool(f())


def _git_repo(tmp_path):
    repo = tmp_path/'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'x@x.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'x'], cwd=repo, check=True)
    (repo/'a.py').write_text('x = 1\n')
    subprocess.run(['git', 'add', 'a.py'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'init'], cwd=repo, check=True)
    return repo


def test_spawn_worktree_isolates_writes_from_the_parent_tree(tmp_path):
    repo = _git_repo(tmp_path)
    parent = Agent(WorkspaceHost([str(repo)]), extensions=False, cfg=tmp_path/'.cfg')
    child, path = parent.spawn_worktree('feature/isolated')

    branch = subprocess.run(['git', 'branch', '--show-current'], cwd=path,
                            capture_output=True, text=True, check=True).stdout.strip()
    assert branch == 'feature/isolated'
    assert child.host.roots[0] == path and path != str(repo)

    child.host.write(str(child.host.roots[0]) + '/b.py', 'y = 2\n')
    assert (repo/'b.py').exists() is False, 'a write in the worktree must not reach the parent tree'

    parent.close()
    child.close()


def test_delegate_worktree_runs_in_the_background_and_reports_the_reply_and_changes(tmp_path):
    parent, _ = fake_agent(cfg=tmp_path)
    scripted, _ = fake_agent(replies=['looked around, nothing to change'])
    parent.spawn_worktree = lambda branch, model=None: (scripted, str(tmp_path/'wt'))

    out = parent._delegate_worktree('review the diff', branch='multirun-x/gpt')
    assert out.startswith('started run_') and 'multirun-x/gpt' in out
    rid = out.split()[1]

    assert until(lambda: rid in parent.background.answers)
    result = parent.background.result(rid)
    assert 'looked around, nothing to change' in result and 'nothing changed' in result

    parent.close()


def test_multirun_starts_one_worktree_delegation_per_model(tmp_path):
    parent, _ = fake_agent(cfg=tmp_path)
    started = []
    parent._delegate_worktree = lambda question, branch='', model=None: (
        started.append((question, branch, model)) or f'started run_{len(started)} on branch {branch}')

    from ramabana.tools import worktree_tools
    multirun = next(t for t in worktree_tools(parent) if t.__name__ == 'multirun')
    out = multirun(models='gpt-4.1, sonnet', prompt='find the bug')
    assert len(started) == 2
    assert started[0][2] == 'gpt-4.1' and started[1][2] == 'sonnet'
    assert started[0][1] != started[1][1], 'each model gets its own branch'
    assert out.count('started run_') == 2

    parent.close()
