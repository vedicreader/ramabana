"A session's starting repository state, read from a real git repository."
import subprocess
from ramabana.agent import repo_state

def test_repo_state(tmp_path):
    repo = tmp_path/'repo'; repo.mkdir()
    def git(*a): return subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q', '-b', 'main'); git('config', 'user.email', 't@example.com'); git('config', 'user.name', 't')
    (repo/'a.py').write_text('x = 1\n'); git('add', '.'); git('commit', '-qm', 'one')
    (repo/'a.py').write_text('x = 2\n'); (repo/'new.py').write_text('')
    s = repo_state(repo)
    assert s['head'] == git('rev-parse', 'HEAD') and s['branch'] == 'main' and s['repo'] == str(repo.resolve())
    assert s['dirty'] == ['a.py']          # untracked files are left out
    (plain := tmp_path/'plain').mkdir()
    assert repo_state(plain) is None
