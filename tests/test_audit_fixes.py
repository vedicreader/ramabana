"""Regressions for the code audit: a turn ends only after its bookkeeping, and bookkeeping errors keep the answer."""
import tomllib
from threading import Thread
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from ramabana.runtime import Compactor
from ramabana.setup import _lock, set_setting, set_table
from ramabana.testing import fake_agent


def test_config_values_may_be_non_ascii_and_concurrent_updates_all_land(tmp_path):
    p = tmp_path/'config.toml'
    set_setting('title', 'a', p); set_setting('title', 'caf\u00e9', p)
    set_table('jobs', {'turn': 'a'}, p); set_table('jobs', {'turn': 'caf\u00e9'}, p)
    got = tomllib.loads(p.read_text())
    assert got['title'] == got['jobs']['turn'] == 'caf\u00e9'
    with ThreadPoolExecutor(4) as ex: list(ex.map(lambda i: set_setting(f'k{i}', i, p), range(60)))
    assert all(tomllib.loads(p.read_text()).get(f'k{i}') == i for i in range(60))


def test_a_history_the_keep_covers_has_nothing_to_compact():
    hist = [{'role': 'user', 'content': 'hi'}]
    b = SimpleNamespace(hist=hist, spec=SimpleNamespace(ctx=0), count_tokens=len, replace_hist=lambda *a: 1/0)
    c = Compactor(strategy='surgical')
    assert c.compact(b, lambda *a: 'S') == '' and 'nothing to compact' in c.note


def test_the_run_is_still_running_while_stop_hooks_fire():
    seen = []
    a, _ = fake_agent(replies=['hello'])
    a.registry.on('stop', lambda ag, text: seen.append(ag.run().terminal))
    a.ask('hi')
    assert seen == [False] and a.run().state == 'completed'


def test_a_checkpoint_that_cannot_be_written_keeps_the_answer(tmp_path):
    a, _ = fake_agent(replies=['the answer'], cfg=tmp_path)
    (tmp_path/'checkpoints').write_text('a file, so mkdir fails')
    begin = a._begin_turn
    a._begin_turn = lambda run: (begin(run), a.before.update({'/proj/a.py': 'x'}))[0]
    out = a.ask('hi')
    assert out.startswith('the answer') and 'checkpoint' in out and a.history[-1]['state'] == 'complete' and a.run().state == 'completed'

import os
from types import SimpleNamespace as NS

import ramabana.monitor as mon
from ramabana.monitor import Monitors
from ramabana.pane import Viewer, _shell_state, _Seen
from ramabana.setup import root_state
from ramabana.testing import FakeBackend, MemHost, SPEC


def test_a_failed_delegation_is_recorded_as_an_error_not_ok():
    h = MemHost({'/proj/a.py': 'one\n'})
    boom = [True]
    def backend():
        if boom.pop(0) if boom else False: raise RuntimeError('boom')
        return FakeBackend(SPEC)
    m = Monitors(h, get_backend=backend); m.add('/proj', 'review', settle=0)
    h.write('/proj/a.py', 'two\n')
    assert [r['status'] for r in m.check(force=True)] == ['error']
    assert m.check(force=True) == [], 'a failed review is reported once, not retried'
    class Bad(FakeBackend):
        def spawn(self, *a, **k): raise RuntimeError('no engine')
    m = Monitors(h, get_backend=lambda: Bad(SPEC)); m.add('/proj', 'review', settle=0)
    h.write('/proj/a.py', 'three\n')
    assert [r['status'] for r in m.check(force=True)] == ['error']


def test_a_same_length_edit_to_an_oversized_file_is_a_change(monkeypatch):
    monkeypatch.setattr(mon, 'SNAP_MAX_BYTES', 10)
    h = MemHost({'/proj/a.py': 'x' * 50})
    m = Monitors(h, get_backend=lambda: FakeBackend(SPEC)); m.add('/proj', 'review', settle=0)
    h.write('/proj/a.py', 'y' * 50)
    assert len(m.check(force=True)) == 1


def test_a_non_git_root_sees_nested_edits(tmp_path):
    (tmp_path/'pkg').mkdir(); f = tmp_path/'pkg'/'a.py'; f.write_text('1')
    for p in (f, tmp_path/'pkg'): os.utime(p, (1000, 1000))
    before = root_state(tmp_path)
    f.write_text('22'); os.utime(f, (2000, 2000)); os.utime(tmp_path/'pkg', (1000, 1000))
    assert root_state(tmp_path) != before
    (tmp_path/'future').write_text('newer')
    os.utime(tmp_path/'future', (4000000000, 4000000000))
    before = root_state(tmp_path)
    f.write_text('33'); os.utime(f, (3000, 3000))
    assert root_state(tmp_path) != before


def test_config_lock_is_reentrant(tmp_path):
    p = tmp_path/'config.toml'
    def nested():
        with _lock(p): set_setting('title', 'nested', path=p)
    worker = Thread(target=nested, daemon=True)
    worker.start(); worker.join(1)
    assert not worker.is_alive()
    assert tomllib.loads((tmp_path/'config.toml').read_text())['title'] == 'nested'


def test_checkpoint_write_and_pruning_failures_are_distinct(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    a.before['/proj/a.py'] = 'before'
    a.current_turn_id = 'new'
    (tmp_path/'checkpoints').write_text('blocks directory creation')
    assert 'not saved' in a._checkpoint()
    (tmp_path/'checkpoints').unlink()
    a.checkpoint_dir.mkdir(parents=True)
    (a.checkpoint_dir/'old.json').write_text('{}')
    monkeypatch.setattr('ramabana.agent.CHECKPOINT_BYTES', 1)
    def denied(p): raise OSError('prune denied')
    monkeypatch.setattr(Path, 'unlink', denied)
    note = a._checkpoint()
    assert 'old checkpoints could not be removed' in note and 'not saved' not in note
    assert (a.checkpoint_dir/'new.json').exists()


def test_a_failed_shell_query_is_retried_and_a_failed_pane_query_keeps_the_pane():
    calls = []
    def cmd_output(rid, n):
        calls.append(rid)
        if len(calls) == 1: raise RuntimeError('transient')
        return 'running', 'out'
    agent, seen = NS(host=NS(cmd_output=cmd_output)), _Seen()
    assert _shell_state(agent, seen, 'cmd_1', 100.0) == ('', '')
    assert _shell_state(agent, seen, 'cmd_1', 105.0) == ('running', 'out')
    v = Viewer.__new__(Viewer); v.pane, v.tmux = {'id': '%9'}, lambda *a: ''
    assert v.alive() is None and v.pane == {'id': '%9'}
