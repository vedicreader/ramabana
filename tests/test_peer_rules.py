"Peer rules: registration, work together mode, limits, targets and the folder guard."
import os, subprocess, sys, time
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
    assert 'hop' in limit_refusal(tmp_path, 'k', Envelope('reply', 'x', {}, hops=HOP_MAX))
    together_on(tmp_path, 'k')
    for i in range(PEER_BUDGET['messages'] - 1): log(tmp_path, Envelope('note', str(i), {'key': 'k'}).dict())
    assert limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'})) == ''
    log(tmp_path, Envelope('note', 'last', {'key': 'k'}).dict())
    assert 'budget' in limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'}))

def test_peer_limits_environment_overrides():
    code = r'''
from tempfile import TemporaryDirectory
from ramabana.peers import *
assert HOP_MAX == 9 and PEER_BUDGET == dict(messages=2, turns=3)
with TemporaryDirectory() as d:
    for i in range(2): log(d, Envelope('note', str(i), {'key': 'k'}).dict())
    assert '2 of 2' in limit_refusal(d, 'k', Envelope('note', 'x', {'key': 'k'}))
    assert limit_refusal(d, 'k', Envelope('reply', 'x', {}, hops=8)) == ''
    assert 'hop' in limit_refusal(d, 'k', Envelope('reply', 'x', {}, hops=9))
'''
    env = dict(os.environ, RAMABANA_PEER_MESSAGES='2', RAMABANA_PEER_ASKS='3', RAMABANA_PEER_HOPS='9')
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    env['RAMABANA_PEER_MESSAGES'] = '0'
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "RAMABANA_PEER_MESSAGES must be a positive integer, not '0'" in result.stderr
    env['RAMABANA_PEER_MESSAGES'] = 'lots'
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "RAMABANA_PEER_MESSAGES must be a positive integer, not 'lots'" in result.stderr
    assert 'invalid literal' not in result.stderr


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


def test_rolling_cap_outside_together_mode(tmp_path):
    for i in range(PEER_BUDGET['messages']): log(tmp_path, Envelope('note', str(i), {'key': 'k'}).dict())
    assert f"budget: {PEER_BUDGET['messages']} of {PEER_BUDGET['messages']} messages sent in 12 h" == limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'}))
    assert limit_refusal(tmp_path, 'o', Envelope('note', 'x', {'key': 'o'})) == '', 'the cap is per sender'

def test_exactly_the_configured_asks_run(tmp_path):
    together_on(tmp_path, 'k', now=time.time() - 1)
    ran = 0
    for i in range(PEER_BUDGET['turns'] + 5):
        log(tmp_path, (e := Envelope('ask', str(i), {'key': 'o'}, to='k')).dict())
        ran += not limit_refusal(tmp_path, 'k', e)
    assert ran == PEER_BUDGET['turns']

def test_guard_skips_home_and_its_parents(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path/'home'))
    (tmp_path/'home'/'repo').mkdir(parents=True)
    rows = [{'key': 'ramabana-r', 'folders': [str(tmp_path/'home'), str(tmp_path)]}]
    assert folder_denial(tmp_path/'home'/'repo'/'a.py', 'claude-s1', rows) is None, 'a session rooted in $HOME or above locks nothing'
    rows = [{'key': 'ramabana-r', 'folders': [str(tmp_path/'home'/'repo')]}]
    assert 'belongs to' in folder_denial(tmp_path/'home'/'repo'/'a.py', 'claude-s1', rows)
    assert folder_denial(tmp_path/'home'/'repo'/'a.py', 'claude-s1', [rows[0] | {'guard': []}]) is None, 'guard wins over folders'


def test_me_warns_when_claude_session_is_not_registered(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'nope')
    assert me()['key'] == 'cli'
    assert capsys.readouterr().err == 'this Claude session is not registered; run ramabana setup peers\n'
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID')
    me(); assert capsys.readouterr().err == ''

def test_codex_shows_no_wake(tmp_path):
    register(tmp_path, 'codex', 'c1', ['/r/a'], os.getpid(), wakes=False)
    register(tmp_path, 'claude', 's1', ['/r/b'], os.getpid())
    lines = peer_lines([{'folder': r['folders'][0]} | r for r in registered(tmp_path)]).splitlines()
    assert '(no wake)' in lines[0] and '(no wake)' not in lines[1]


def test_reply_refused_by_hop_limit_reaches_asker_as_failed(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    log(tmp_path, (ask := Envelope('ask', 'one more round', me(tmp_path), 'claude-s1', hops=HOP_MAX - 1)).dict())
    said = tell('cli', 'done', 'reply', me(tmp_path, 's1'), thread=ask.thread, cfg=tmp_path)
    [r] = take(tmp_path, 'cli')
    assert said.startswith('not sent to cli: hop limit') and (r.kind, r.thread) == ('reply', ask.thread) and r.text.startswith('failed: hop limit'), (said, r.text)
