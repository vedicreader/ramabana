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
    m, frm = PEER_BUDGET['messages'], {'key': 'k', 'name': 'orgs · claude'}
    for i in range(m): log(tmp_path, Envelope('note', str(i), frm, to='y' if i == 0 else 'x', to_frm={'name': 'Y' if i == 0 else 'X'}).dict())
    assert f"budget: orgs · claude (k) sent {m} of {m} messages in 12 h: {m - 1} to X, 1 to Y" == limit_refusal(tmp_path, 'k', Envelope('note', 'x', frm))
    assert limit_refusal(tmp_path, 'o', Envelope('note', 'x', {'key': 'o'})) == '', 'the cap is per sender'

def test_together_messages_raise_the_cap_for_partners(tmp_path):
    m = PEER_BUDGET['messages']
    say = lambda who: Envelope('note', 'x', {'key': 'k', 'name': 'orgs'}, to=who, to_frm={'name': f'{who} · claude'})
    together_on(tmp_path, 'k', ['leela'], now=time.time() - 1, messages=m + 5)
    for i in range(m + 4): log(tmp_path, say('leela').dict())
    assert limit_refusal(tmp_path, 'k', say('leela')) == ''
    log(tmp_path, say('leela').dict())
    assert f'sent {m + 5} of {m + 5}' in limit_refusal(tmp_path, 'k', say('leela'))
    assert limit_refusal(tmp_path, 'k', say('abhyasa')) == '', 'others keep the normal cap, which partners do not use'
    for i in range(m): log(tmp_path, say('abhyasa').dict())
    assert f'sent {m} of {m}' in limit_refusal(tmp_path, 'k', say('abhyasa'))
    together_on(tmp_path, 'k', ['leela'], now=time.time() - 1)
    assert 'budget' in limit_refusal(tmp_path, 'k', say('leela')), 'without `messages` the normal cap holds'

def test_last_hop_is_flagged_to_sender_and_receiver(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    hint = f'(hop {HOP_MAX - 1} of {HOP_MAX})'
    said = tell('s1', 'x', 'ask', me(tmp_path), thread='t', hops=HOP_MAX - 1, cfg=tmp_path)
    assert 'last message this thread allows' in said and hint in said, said
    first = tell('s1', 'x', 'ask', me(tmp_path), cfg=tmp_path)
    assert 'last message' not in first, first
    assert hint in peer_text(Envelope('ask', 'x', {}, hops=HOP_MAX - 1))
    assert 'last message' not in peer_text(Envelope('ask', 'x', {}, hops=1))

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


def test_budget_used_matches_refusal(tmp_path):
    m = PEER_BUDGET['messages']
    for i in range(m): log(tmp_path, Envelope('note', str(i), {'key': 'k'}).dict())
    n, cap, asks, turns = budget_used(tmp_path, 'k')
    assert (n, cap, asks, turns) == (m, m, 0, PEER_BUDGET['turns'])
    assert f'sent {n} of {cap} messages' in limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'}))
    assert budget_line(tmp_path, 'k') == f"{m} of {m} messages, 0 of {turns} asks"
    together_on(tmp_path, 'k', now=time.time() - 1)
    for i in range(3): log(tmp_path, Envelope('ask', str(i), {'key': 'o'}, to='k').dict())
    assert budget_used(tmp_path, 'k')[2] == 3

def test_together_raise_keeps_started(tmp_path, capsys):
    assert together_raise(tmp_path, 'k', 99) is None
    st = together_on(tmp_path, 'k', now=time.time() - 50, messages=10)
    assert together_raise(tmp_path, 'k', 99) == st | dict(messages=99)
    assert together_state(tmp_path, 'k')['started'] == st['started']
    assert peers_cli(['together', 'raise'], cfg=tmp_path) == 2

def test_new_session_in_same_folder_inherits_the_mode(tmp_path):
    register(tmp_path, 'claude', 'old', ['/r/abhyasa'], os.getpid())
    st = together_on(tmp_path, 'claude-old', ['leela'], until='23:59')
    unregister(tmp_path, 'claude', 'old')   # the session ended; its mode stays for a while
    register(tmp_path, 'claude', 'new', ['/r/abhyasa'], os.getpid())
    new = together_state(tmp_path, 'claude-new')
    assert new['carried'] == 'claude-old' and new['until'] == st['until'] and new['partners'] == ['leela'] and 'folders' not in new
    register(tmp_path, 'claude', 'other', ['/r/leela'], os.getppid())
    assert together_state(tmp_path, 'claude-other') is None, 'another folder takes no mode'
    register(tmp_path, 'codex', 'live', ['/r/abhyasa'], os.getpid())
    assert together_state(tmp_path, 'codex-live')['carried'] == 'claude-new', 'a live session in the folder is copied'
    assert together_state(tmp_path, 'claude-new') is not None

def test_tell_to_unknown_target_lists_live_peers(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    with pytest.raises(LookupError, match=r"no live session 'zz'; live peers: 1 abhyasa · claude"): tell('zz', 'x', frm=me(tmp_path), cfg=tmp_path)
    with pytest.raises(LookupError, match='The cli has no session; reply with --reply-to'): tell('cli', 'x', frm=me(tmp_path), cfg=tmp_path)

def test_last_hop_starts_a_summary_thread(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    tell('s1', 'build the card', 'ask', me(tmp_path), thread='t7', cfg=tmp_path)
    assert not [r for r in read_log(tmp_path) if r.get('event') == 'summary']
    said = tell('s1', 'one more thing', 'ask', me(tmp_path), thread='t7', hops=HOP_MAX - 1, cfg=tmp_path)
    [row] = [r for r in read_log(tmp_path) if r.get('event') == 'summary']
    assert row['thread'] == 't7' and 'build the card' in row['text'] and 'one more thing' in row['text'] and row['text'] in said
    assert 'hop limit' in tell('s1', 'again', 'ask', me(tmp_path), thread='t7', hops=HOP_MAX, cfg=tmp_path), 'the cap stays'

def test_handoff_has_three_parts_and_failed_reply_gets_one(tmp_path, monkeypatch):
    p = write_handoff(tmp_path, 'th', 'step 1 done', 'a.py | 2 +-', 'Which name?')
    assert [l for l in p.read_text().splitlines() if l.startswith('## ')] == ['## Plan', '## Diff', '## Open questions']
    assert read_handoff(tmp_path)[0] == p and read_handoff(tmp_path, 'zz') is None
    repo = tmp_path/'repo'; repo.mkdir()
    git = lambda *a: subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True, check=True).stdout
    git('init', '-q'); (repo/'a.py').write_text('x\n'); git('add', '.'); git('commit', '-qm', 'one'); (repo/'a.py').write_text('y\n')
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path/'peers'))
    d = peers_dir(); register(d, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    frm = dict(kind='claude', session='w', key='claude-w', name='w', folders=[str(repo)])
    tell('s1', 'failed: tests broke', 'reply', frm, thread='th9', cfg=tmp_path/'cfg')
    h = read_handoff(repo, 'th9')
    assert h and '-x' in h[1] and '+y' in h[1] and 'tests broke' in h[1]
    [e] = take(d, 'claude-s1')
    assert 'handoff:' in e.text and 'handoff-th9.md' in e.text


def _repo(tmp_path):
    git = lambda *a: subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True, check=True).stdout.strip()
    git('init', '-q'); (tmp_path/'a.py').write_text('a\n'); (tmp_path/'b.py').write_text('b\n'); git('add', '.'); git('commit', '-qm', 'base')
    return git

def test_commit_helper_commits_named_paths_only(tmp_path):
    git = _repo(tmp_path)
    (tmp_path/'a.py').write_text('a2\n'); (tmp_path/'b.py').write_text('b2\n'); (tmp_path/'new.py').write_text('n\n')
    env = dict(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
    for k, v in env.items(): os.environ[k] = v
    try: commit_paths(['a.py', 'new.py'], cwd=tmp_path)
    finally: [os.environ.pop(k) for k in env]
    assert git('show', '--name-only', '--format=%s', 'HEAD').splitlines() == ['Save a.py, new.py', '', 'a.py', 'new.py']
    assert git('status', '--short') == 'M b.py', 'the other file stays changed'
    assert 'Co-Authored' not in git('log', '-1', '--format=%B')
    with pytest.raises(RuntimeError): commit_paths(['b.py'], cwd=tmp_path/'nowhere')

def test_commit_cli_clears_the_edit_record(tmp_path, monkeypatch):
    repo = tmp_path/'r'; repo.mkdir(); _repo(repo)
    (repo/'a.py').write_text('a2\n')
    d = tmp_path/'peers'; d.mkdir()
    register(d, 'claude', 's1', [str(repo)], os.getpid()); note_edits(d, 'claude-s1', [repo/'a.py'])
    monkeypatch.chdir(repo)
    monkeypatch.setenv('GIT_AUTHOR_NAME', 't'); monkeypatch.setenv('GIT_AUTHOR_EMAIL', 't@t'); monkeypatch.setenv('GIT_COMMITTER_NAME', 't'); monkeypatch.setenv('GIT_COMMITTER_EMAIL', 't@t')
    assert peers_cli(['commit', 'a.py', '--message', 'Fix a'], cfg=tmp_path) == 0
    assert 'edits' in registered(d)[0] and registered(d)[0]['edits'] == {}

def test_checkpoint_commits_to_wip_branch_and_never_pushes(tmp_path, monkeypatch):
    git = _repo(tmp_path)
    remote = tmp_path.parent/(tmp_path.name + '-remote.git'); subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    git('remote', 'add', 'origin', str(remote))
    head, branch = git('rev-parse', 'HEAD'), git('branch', '--show-current')
    (tmp_path/'a.py').write_text('wip\n'); (tmp_path/'u.py').write_text('u\n')
    for k in ('NAME', 'EMAIL'): monkeypatch.setenv(f'GIT_AUTHOR_{k}', 't'); monkeypatch.setenv(f'GIT_COMMITTER_{k}', 't')
    sha = checkpoint(tmp_path, 'th1')
    assert git('rev-parse', 'wip/th1') == sha and git('rev-parse', 'wip/th1^') == head
    assert git('show', f'{sha}:a.py') == 'wip' and git('show', f'{sha}:u.py') == 'u'
    assert git('rev-parse', 'HEAD') == head and git('branch', '--show-current') == branch, 'the working branch does not move'
    assert git('status', '--short').splitlines() == ['M a.py', '?? u.py'], 'the index and files stay as they were'
    assert git('ls-remote', 'origin') == '', 'nothing is pushed'
    (tmp_path/'a.py').write_text('wip2\n')
    assert git('rev-parse', f'{checkpoint(tmp_path, "th1")}^') == sha, 'the next checkpoint builds on the first'
    with pytest.raises(RuntimeError): checkpoint(tmp_path, 'bad name')
