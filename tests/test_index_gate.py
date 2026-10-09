"The code index runs only when a package or an indexed root changed, and says why in `<cfg>/kosha.log`."
import subprocess, sys, textwrap

import pytest

from fastcore.xtras import Path

from ramabana import setup
from ramabana.cli import sync_index
from ramabana.setup import KOSHA_LOG, index_gate, index_state, last_index, save_index

def git(root, *args): subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)

def repo(tmp_path, name='leela'):
    r = tmp_path/name
    r.mkdir()
    git(r, 'init', '-q'); (r/'a.py').write_text('x = 1\n')
    git(r, 'add', '.'); git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'one')
    return r

def site(tmp_path, *pkgs):
    d = tmp_path/'site'
    d.mkdir(exist_ok=True)
    for p in pkgs: (d/f'{p}.dist-info').mkdir()
    return d

@pytest.fixture(autouse=True)
def env_db(tmp_path, monkeypatch):
    "Kosha's env db, present unless a test removes it."
    p = tmp_path/'xdg'/'kosha'/'env.db'
    p.parent.mkdir(parents=True); p.write_text('')
    monkeypatch.setattr(setup, 'kosha_env_db', lambda: p)
    return p

def indexed(*roots):
    "What a real sync leaves in each root."
    for r in roots: (Path(r)/'.kosha').mkdir(exist_ok=True); (Path(r)/'.kosha'/'code.db').write_text('')

class Host:
    "A fake kosha: records syncs, writes each root's code db, and reports ready."
    index_ready, search_note = True, 'ok'
    def __init__(self, *roots): self.roots, self.synced, self.opened = [str(r) for r in roots], 0, 0
    def sync_index(self): self.synced += 1; indexed(*self.roots)
    def wait_index(self, timeout=None): return True
    def open_index(self): self.opened += 1

def settle(cfg, n):
    import time
    for _ in range(200):
        if len((cfg/KOSHA_LOG).read_text().splitlines() if (cfg/KOSHA_LOG).exists() else []) >= n: return
        time.sleep(.01)

def test_a_failed_sync_saves_no_state_so_the_next_start_runs(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    h = Host(r); h.index_ready, h.search_note = False, 'Kosha unavailable (boom)'
    sync_index(h, cfg, dirs=[d]); settle(cfg, 1)
    assert 'failed: Kosha unavailable (boom)' in last_index(cfg)
    assert sync_index(h, cfg, dirs=[d]) == 'run'

def test_an_unchanged_start_imports_no_kosha(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    sync_index(Host(r), cfg, dirs=[d]); settle(cfg, 1)
    env = setup.kosha_env_db()
    code = f'''
    import sys, time
    from ramabana.agent import mk_agent
    from ramabana.cli import start_agent
    from ramabana.testing import FakeBackend
    from ramabana import setup
    setup.kosha_env_db = lambda: __import__('pathlib').Path({str(env)!r})
    _ps = setup.pkg_state
    setup.pkg_state = lambda dirs=None: _ps(dirs or [{str(d)!r}])
    a, h = mk_agent([{str(r)!r}], web=False, cfg=__import__('pathlib').Path({str(cfg)!r}))
    a._be = lambda job='turn': FakeBackend()
    start_agent(a)
    time.sleep(.3)
    print(sorted(m for m in ('kosha', 'litesearch', 'model2vec') if m in sys.modules), len(h._indexes), h.index_ready)
    '''
    out = subprocess.run([sys.executable, '-c', textwrap.dedent(code)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.strip() == '[] 1 True', out.stdout
    assert last_index(cfg).split(' · ')[1] == 'skip'

def test_uncommitted_edits_change_the_worktree_digest(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    indexed(r)
    save_index(cfg, index_state([r], [d]))
    assert index_gate(cfg, [r], [d])[1] == '', 'the code db kosha writes is not an edit'
    (r/'a.py').write_text('x = 2\n')
    assert index_gate(cfg, [r], [d])[1] == 'leela worktree changed'
    save_index(cfg, index_state([r], [d]))
    import os, time
    os.utime(r/'a.py', (time.time() + 5, time.time() + 5))
    assert index_gate(cfg, [r], [d])[1] == 'leela worktree changed', 'a second edit to an edited file'
