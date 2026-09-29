"The code index runs only when a package or an indexed root changed, and says why in `<cfg>/kosha.log`."
import json, subprocess, sys, textwrap

from fastcore.xtras import Path

from ramabana import setup
from ramabana.cli import start_agent, sync_index
from ramabana.setup import KOSHA_LOG, index_changes, index_state, last_index, log_index

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

class Host:
    "A fake kosha: records syncs, and reports ready."
    index_ready, search_note = True, 'ok'
    def __init__(self, *roots): self.roots, self.synced, self.opened = [str(r) for r in roots], 0, 0
    def sync_index(self): self.synced += 1
    def wait_index(self, timeout=None): return True
    def open_index(self): self.opened += 1

def settle(cfg, n):
    import time
    for _ in range(200):
        if len((cfg/KOSHA_LOG).read_text().splitlines() if (cfg/KOSHA_LOG).exists() else []) >= n: return
        time.sleep(.01)

def test_first_run_then_unchanged_skips(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    h = Host(r)
    assert sync_index(h, cfg, dirs=[d]) == 'run' and h.synced == 1
    settle(cfg, 1)
    assert sync_index(h, cfg, dirs=[d]) == 'skip' and h.synced == 1 and h.opened == 1
    first, second = (cfg/KOSHA_LOG).read_text().splitlines()
    assert first.split(' · ')[1:3] == ['run', 'first sync'] and second.split(' · ')[1:3] == ['skip', 'unchanged']

def test_a_package_added_or_a_moved_head_runs(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    h = Host(r)
    sync_index(h, cfg, dirs=[d]); settle(cfg, 1)
    site(tmp_path, 'foo-1.2')
    assert sync_index(h, cfg, dirs=[d]) == 'run'; settle(cfg, 2)
    assert (cfg/KOSHA_LOG).read_text().splitlines()[-1].split(' · ')[2] == 'packages changed: +foo 1.2'
    old = index_state([r], [d])['roots'][str(r)]['head']
    (r/'b.py').write_text('y = 2\n'); git(r, 'add', '.'); git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'two')
    assert sync_index(h, cfg, dirs=[d]) == 'run'; settle(cfg, 3)
    new = index_state([r], [d])['roots'][str(r)]['head']
    assert (cfg/KOSHA_LOG).read_text().splitlines()[-1].split(' · ')[2] == f'leela HEAD {old[:4]}→{new[:4]}'
    assert h.synced == 3

def test_a_failed_sync_saves_no_state_so_the_next_start_runs(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    h = Host(r); h.index_ready, h.search_note = False, 'Kosha unavailable (boom)'
    sync_index(h, cfg, dirs=[d]); settle(cfg, 1)
    assert 'failed: Kosha unavailable (boom)' in last_index(cfg)
    assert sync_index(h, cfg, dirs=[d]) == 'run'

def test_changes_outside_git_and_new_roots():
    assert index_changes(None, {'packages': {}, 'roots': {}}) == 'first sync'
    old = {'packages': {'a-1': 1.0}, 'roots': {'/x/proj': {'mtime': 1.0}}}
    new = {'packages': {'a-1': 2.0, 'b-2': 1.0}, 'roots': {'/x/proj': {'mtime': 2.0}, '/y/other': {'mtime': 1.0}}}
    assert index_changes(old, new) == 'packages changed: +b 2 ~a 1; proj files changed; other new root'
    assert index_changes(new, new) == ''

def test_the_log_line_and_the_doctor_line(tmp_path, capsys):
    cfg = tmp_path/'cfg'
    assert last_index(cfg) == ''
    log_index(cfg, 'skip', 'unchanged', 0.0123)
    when, decision, why, took = last_index(cfg).split(' · ')
    assert len(when) == 19 and (decision, why, took) == ('skip', 'unchanged', '0.01s')
    s = setup.Setup(cfg, environ={'PATH': '/bin'}, argv=['x'], which=lambda n: None, run=None)
    s.offer_install = lambda force=False: None
    s.doctor()
    assert capsys.readouterr().out.splitlines()[-1] == f'kosha: {last_index(cfg)}'

def test_an_unchanged_start_imports_no_kosha(tmp_path):
    r, d, cfg = repo(tmp_path), site(tmp_path, 'fastcore-1.8.0'), tmp_path/'cfg'
    sync_index(Host(r), cfg, dirs=[d]); settle(cfg, 1)
    code = f'''
    import sys, time
    from ramabana.agent import mk_agent
    from ramabana.cli import start_agent
    from ramabana.testing import FakeBackend
    from ramabana import setup
    setup.site_dirs = lambda: [{str(d)!r}]
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
