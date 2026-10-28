"The morning report: one table row per thread, a glossary of the terms used, and a saved file."
import os, subprocess, time
from pathlib import Path

import pytest

import ramabana.peer_report as pr
from ramabana.peers import peers_dir, log, read_log

A, B, C = {'key': 'claude-1', 'name': 'Leela', 'kind': 'claude'}, {'key': 'ramabana-2', 'name': 'Ramabana', 'kind': 'ramabana'}, {'key': 'codex-3', 'name': 'Abhyasa', 'kind': 'codex'}

def env(id, kind, frm, to, text, thread=None, at=100., hops=0, **kw):
    return dict(id=id, kind=kind, to=to, text=text, thread=thread or id, at=at, hops=hops, changes=[], proof=[]) | {'from': frm} | kw

ROWS = [
    env('a1', 'ask', A, B['key'], 'Add the tell shortcut', at=101),
    env('a2', 'reply', B, A['key'], 'Done', 'a1', at=102, hops=1, changes=['ramabana/cli.py'], proof=['pytest: 12 passed']),
    env('b1', 'ask', B, C['key'], 'Fix the card | layout', at=103),
    env('b2', 'reply', C, B['key'], 'Done', 'b1', at=104, hops=1, changes=['card.py']),
    env('c1', 'ask', A, C['key'], 'Rename the module', at=105),
    env('c2', 'reply', C, A['key'], 'Which name?', 'c1', at=106, hops=1),
    {'event': 'refused', 'key': 'codex-3', 'why': 'hop limit: 6 of 6 hops used', 'thread': 'c1', 'at': 107.},
]
STUB = lambda ts, agent=None: ('- Ramabana added a shortcut.', '- Read the diff: ramabana/cli.py')

@pytest.fixture
def peers(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path/'peers'))
    d = peers_dir()
    for r in ROWS: log(d, r)
    return d

def test_threads_states():
    ts = {t['id']: t for t in pr.threads(ROWS)}
    assert [ts[k]['state'] for k in ('a1', 'b1', 'c1')] == ['replied', 'not proven', 'stopped']
    assert ts['a1']['asker'] == 'Leela' and ts['a1']['worker'] == 'Ramabana' and ts['a1']['proof'] == ['pytest: 12 passed']
    only_ask = pr.threads([env('d1', 'ask', A, B['key'], 'Wait for me')])
    assert only_ask[0]['state'] == 'waiting'
    no = pr.threads([ROWS[0], env('r', 'reply', B, A['key'], 'Refused: I cannot change that folder', 'a1')])
    assert no[0]['state'] == 'refused'

def test_table_columns_and_rows():
    lines = pr.table(pr.threads(ROWS)).splitlines()
    assert lines[0] == '| Asked by | Done by | What | Changed | Proof | State |'
    assert len(lines) == 2 + 3
    assert 'Fix the card \\| layout' in lines[3] and 'not proven' in lines[3]

def test_glossary_only_used_terms():
    g = pr.glossary('This ask has one reply in a thread.')
    assert all(t in g for t in ('ask', 'reply', 'thread')) and 'budget' not in g and 'hop' not in g
    assert set(pr.GLOSSARY) >= {'peer', 'note', 'ask', 'reply', 'thread', 'hop', 'work together mode', 'proof', 'budget'}

def test_actions_always_list_unproven_and_stopped(peers, monkeypatch):
    monkeypatch.setattr(pr, 'summarise', lambda ts, agent=None: ('', ''))
    out = pr.report(0)
    acts = out.split('## Your actions')[1].split('## Glossary')[0]
    assert 'Fix the card' in acts and 'Rename the module' in acts
    assert 'Add the tell shortcut' not in acts

def test_failed_summary_still_saves(peers, monkeypatch):
    def boom(ts, agent=None): raise RuntimeError('no model')
    monkeypatch.setattr(pr, 'summarise', boom)
    out = pr.report(0)
    assert 'examples are missing' in out and '| Asked by |' in out and '## Glossary' in out

def test_report_sections(peers, monkeypatch):
    monkeypatch.setattr(pr, 'summarise', STUB)
    out = pr.report(0)
    assert out.startswith('# Night of ') and all(h in out for h in ('## What changed', '## Your actions', '## Glossary'))
    assert 'Ramabana added a shortcut.' in out and 'Read the diff' in out

def test_save_report_reuses_fresh_file(peers, monkeypatch):
    monkeypatch.setattr(pr, 'summarise', STUB)
    p = pr.save_report(0)
    assert p.parent == peers/'reports' and p.suffix == '.md' and 'Night of' in p.read_text()
    p.write_text('kept'); os.utime(p, (time.time(), time.time()))
    assert pr.save_report(0).read_text() == 'kept'
    log(peers, env('z1', 'note', A, B['key'], 'new', at=time.time()+5))
    assert 'Night of' in pr.save_report(0).read_text()

def _git(repo, *a): return subprocess.run(['git', '-C', str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()

def test_checked_changes_marks_missing_commit(tmp_path):
    _git(tmp_path, 'init', '-q')
    (tmp_path/'a.py').write_text('x')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'one')
    sha = _git(tmp_path, 'rev-parse', 'HEAD')
    t = dict(changes=[sha[:8], 'deadbeef1', 'a.py', 'gone.py'], folders=[str(tmp_path)])
    out = pr.checked_changes(t, time.time()-3600)
    assert out == [sha[:8], 'deadbeef1 (not in git)', 'a.py', 'gone.py (not in git)']
    assert pr.checked_changes(t, time.time()+3600) == [f'{c} (not in git)' for c in t['changes']]
    assert pr.checked_changes(dict(changes=['x.py'], folders=[]), 0) == ['x.py']

def test_report_cli(peers, monkeypatch, capsys):
    monkeypatch.setattr(pr, 'summarise', STUB)
    log(peers, {'event': 'together_end', 'key': 'claude-1', 'started': 50., 'at': 90.})
    assert pr.report_cli([]) == 0
    assert '# Night of' in capsys.readouterr().out
    assert pr.report_cli(['--since', '104', '--save']) == 0
    assert capsys.readouterr().out.strip().endswith('.md')

def test_run_cli_dispatches_report(peers, monkeypatch):
    from ramabana.setup import run_cli
    monkeypatch.setattr('sys.argv', ['ramabana', 'report', '--since', 'soon'])
    assert run_cli() == 2

def test_refused_needs_the_exact_prefix():
    st = lambda text: pr.threads([ROWS[0], env('r', 'reply', B, A['key'], text, 'a1', proof=['p'])])[0]['state']
    assert st('refused: not my repo') == 'refused'
    assert st("I can't reproduce it, but I fixed X") == 'replied'

def test_save_report_rebuilds_degraded_and_keys_on_since(peers):
    def boom(ts, agent=None): raise RuntimeError('no model')
    p = pr.save_report(0, summary=boom)
    assert pr.MISSING in p.read_text() and 'RuntimeError: no model' in p.read_text()
    assert pr.save_report(0, summary=STUB) == p and pr.MISSING not in p.read_text()
    assert pr.save_report(3600, summary=STUB) != p
    assert p.name.endswith('-%s.md' % time.strftime('%H%M', time.localtime(0)))

def test_waiting_thread_shows_receiver_name_and_folder():
    named = env('x', 'reply', dict(C, folders=['/tmp/abhyasa']), A['key'], 'Done', 'b1', proof=['p'])
    ts = pr.threads([*ROWS, named, env('d1', 'ask', A, C['key'], 'Wait for me')])
    t = [t for t in ts if t['id'] == 'd1'][0]
    assert t['worker'] == 'Abhyasa'
    ts = pr.threads([env('d1', 'ask', A, C['key'], 'Wait for me')], known={C['key']: dict(C, folders=['/tmp/abhyasa'])})
    assert pr.derived_actions(ts) == ["- Get an answer to 'Wait for me': Abhyasa (abhyasa)"]

def test_no_made_up_asker_or_ask():
    t, = pr.threads([ROWS[1]])
    assert (t['asker'], t['worker'], t['ask']) == ('claude-1', 'Ramabana', pr.NO_ASK)
    t, = pr.threads([ROWS[-1]])
    assert (t['asker'], t['worker'], t['ask']) == ('?', '', 'hop limit: 6 of 6 hops used')

def test_checked_changes_skips_non_repo_and_missing_git(tmp_path, monkeypatch):
    t = dict(changes=['a.py'], folders=[str(tmp_path)])
    assert pr.checked_changes(t, 0) == ['a.py']
    def nogit(*a, **k): raise FileNotFoundError('git')
    monkeypatch.setattr(pr.subprocess, 'run', nogit)
    assert pr.checked_changes(t, 0) == ['a.py']

def test_no_threads_skips_the_model(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    def boom(*a, **k): raise AssertionError('called')
    assert 'No thread in this time.' in pr.report(0, summary=boom)

def test_the_summary_with_no_agent_given_uses_the_agent_mk_agent_makes(monkeypatch):
    "`mk_agent` gives `(agent, host)`; the report used the pair as the agent, and every morning said `'tuple' object has no attribute 'oneshot'`."
    import ramabana.agent as ag
    class Agent:
        def oneshot(self, prompt, sp='', job='oneshot'): return 'EXAMPLES\n- Ramabana added a shortcut.\nACTIONS\n- Read the diff: ramabana/cli.py'
    monkeypatch.setattr(ag, 'mk_agent', lambda *a, **kw: (Agent(), object()))
    ts = pr.threads(ROWS, {r['key']: r for r in (A, B, C)})
    assert pr.summarise(ts) == ('- Ramabana added a shortcut.', '- Read the diff: ramabana/cli.py')
