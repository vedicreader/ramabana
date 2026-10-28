"Peer rules: registration, work together mode, limits, targets and the folder guard."
import os
from datetime import datetime

import pytest

from ramabana.peers import *


def test_registered_drops_dead_pid(tmp_path):
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    register(tmp_path, 'claude', 's2', ['/r/leela'], 999999)
    assert [r['key'] for r in registered(tmp_path)] == ['claude-s1']
    assert not (tmp_path/'claude-s2.json').exists()

def test_reregister_same_pid_replaces_old(tmp_path):
    register(tmp_path, 'claude', 'old', ['/r/a'], os.getpid())
    register(tmp_path, 'claude', 'new', ['/r/a'], os.getpid())
    assert [r['session'] for r in registered(tmp_path)] == ['new']

def test_until_rolls_to_next_day(tmp_path):
    late, early = datetime(2026, 10, 28, 23).timestamp(), datetime(2026, 10, 28, 6).timestamp()
    assert together_on(tmp_path, 'k', until='07:00', now=late)['until'] == datetime(2026, 10, 29, 7).timestamp()
    assert together_on(tmp_path, 'k', until='07:00', now=early)['until'] == datetime(2026, 10, 28, 7).timestamp()
    assert together_on(tmp_path, 'k', now=late)['until'] == late + 12*3600

def test_expired_together_ends_and_logs(tmp_path):
    together_on(tmp_path, 'k', now=0)
    assert together_state(tmp_path, 'k', now=13*3600) is None
    assert read_log(tmp_path)[-1]['event'] == 'together_end'

def test_hop_and_budget_refusals(tmp_path):
    assert 'hop' in limit_refusal(tmp_path, 'k', Envelope('reply', 'x', {}, hops=6))
    together_on(tmp_path, 'k')
    for i in range(40): log(tmp_path, Envelope('note', str(i), {'key': 'k'}).dict())
    assert 'budget' in limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'}))

def test_match_peer_by_number_id_and_repo():
    rows = [{'session': 'a1', 'key': 'claude-a1', 'folders': ['/r/sanketa']}, {'session': 'b2', 'key': 'ramabana-b2', 'folders': ['/r/leela']}]
    assert match_peer(rows, '2')['session'] == 'b2' and match_peer(rows, 'sanketa')['session'] == 'a1'
    with pytest.raises(LookupError, match='1 .*sanketa'): match_peer(rows + [{**rows[0], 'session': 'c3', 'key': 'claude-c3'}], 'sanketa')

def test_guard_resolves_paths(tmp_path, monkeypatch):
    (own := tmp_path/'leela').mkdir(); (link := tmp_path/'l').symlink_to(own)
    rows = [{'key': 'ramabana-b2', 'folders': [str(own)]}, {'key': 'claude-a1', 'folders': [str(tmp_path/'abhyasa')]}]
    monkeypatch.chdir(tmp_path)
    assert folder_denial('leela/x.py', 'claude-a1', rows) and folder_denial(link/'x.py', 'claude-a1', rows)
    assert folder_denial('leela/x.py', 'ramabana-b2', rows) is None
    assert folder_denial('leela/x.py', 'claude-a1', rows + [{'key': 'claude-a1', 'folders': [str(own)]}]) is None

def test_split_proof():
    body, ch, pr = split_proof('Done.\nchanges: rupaka/card.py; abc123\nProof: uv run pytest -q → 12 passed')
    assert body == 'Done.' and ch == ['rupaka/card.py', 'abc123'] and pr == ['uv run pytest -q → 12 passed']


def test_registered_skips_corrupt_files(tmp_path):
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    (tmp_path/'claude-bad.json').write_text('{not json')
    (tmp_path/'claude-part.json').write_text('{"kind": "claude"}')
    register(tmp_path, 'claude', 's2', ['/r/leela'], os.getpid())
    assert [r['session'] for r in registered(tmp_path)] == ['s2']
