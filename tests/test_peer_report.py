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
    assert lines[0] == '| Asked by | Done by | What | Changed | Proof | Replies | State |'
    assert len(lines) == 2 + 3
    assert 'Fix the card \\| layout' in lines[3] and 'not proven' in lines[3]

def test_glossary_only_used_terms():
    g = pr.glossary('This ask has one reply in a thread.')
    assert all(t in g for t in ('ask', 'reply', 'thread')) and 'budget' not in g and 'hop' not in g
    assert set(pr.GLOSSARY) >= {'peer', 'note', 'ask', 'reply', 'thread', 'hop', 'work together mode', 'proof', 'budget'}

def test_actions_always_list_unproven_and_stopped(peers, monkeypatch):
    monkeypatch.setattr(pr, 'summarise', lambda ts, agent=None: ('', ''))
    out = pr.report(0, model=True)
    acts = out.split('## Your actions')[1].split('## Glossary')[0]
    assert 'Fix the card' in acts and 'Rename the module' in acts
    assert 'Ask for proof of' in acts and "review 'Add the tell shortcut'" in acts and 'Get an answer' not in acts, 'a thread with proof but no reviewer gets a review action only'

def test_failed_summary_still_saves(peers, monkeypatch):
    def boom(ts, agent=None): raise RuntimeError('no model')
    monkeypatch.setattr(pr, 'summarise', boom)
    out = pr.report(0, model=True)
    assert pr.MISSING in out and 'RuntimeError: no model' in out and '| Asked by |' in out and '## Glossary' in out
    changed = out.split('## What changed')[1].split('## Your actions')[0]
    assert '- Ramabana for Leela: ramabana/cli.py (proof: pytest: 12 passed)' in changed and '- Abhyasa for Ramabana: card.py (proof: none)' in changed

def test_report_sections(peers, monkeypatch):
    monkeypatch.setattr(pr, 'summarise', STUB)
    out = pr.report(0, model=True)
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
    t, = pr.threads([ROWS[1]], full=ROWS[2:])
    assert (t['asker'], t['worker'], t['ask']) == ('claude-1', 'Ramabana', pr.NO_ASK)
    t, = pr.threads([ROWS[-1]])
    assert (t['asker'], t['worker'], t['ask']) == ('?', '', 'hop limit: 6 of 6 hops used')

def test_ask_before_since_is_found_in_the_whole_log(peers, monkeypatch):
    t, = pr.threads([ROWS[1]], full=ROWS)
    assert (t['asker'], t['worker'], t['ask'], t['state']) == ('Leela', 'Ramabana', 'Add the tell shortcut', 'replied')
    monkeypatch.setattr(pr, 'summarise', STUB)
    out = pr.report(101.5, model=True)
    assert 'Add the tell shortcut' in out and pr.NO_ASK not in out and '| Leela | Ramabana |' in out

def test_failed_reply_is_failed_not_unproven():
    ts = pr.threads([ROWS[0], env('r', 'reply', B, A['key'], 'failed: cancelled by the user', 'a1')])
    assert ts[0]['state'] == 'failed'
    assert pr.derived_actions(ts) == ["- Re-send or drop 'Add the tell shortcut': Ramabana"]

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


def test_report_with_no_model_makes_no_oneshot_call(peers, monkeypatch):
    import ramabana.agent as ag
    def boom(*a, **k): raise AssertionError('a model was made')
    monkeypatch.setattr(ag, 'mk_agent', boom)
    out = pr.report(0, sessions=[])
    assert pr.MISSING not in out and '- Ramabana for Leela: ramabana/cli.py (proof: pytest: 12 passed)' in out
    with pytest.raises(AssertionError): pr.summarise(pr.threads(ROWS))
    assert pr.MISSING in pr.report(0, model=True, sessions=[]), 'the model opt-in calls mk_agent and falls back when it fails'

def test_report_lists_the_ask_reply_changes_and_proof(peers):
    out = pr.report(0, sessions=[])
    row = next(l for l in out.splitlines() if 'Add the tell shortcut' in l and l.startswith('|'))
    assert [c.strip() for c in row.strip('|').split('|')] == ['Leela', 'Ramabana', 'Add the tell shortcut', 'ramabana/cli.py', 'pytest: 12 passed', '1', 'replied']
    assert '| Replies |' in out.splitlines()[2]

def test_report_lists_subagent_runs_from_a_given_list(peers):
    runs = [dict(first='Find the old tests', at=3600., size=4096, path='x')]
    out = pr.report(0, sessions=runs)
    assert '## Your own subagent runs' in out and 'Find the old tests' in out and '4 KB' in out
    assert '## Your own subagent runs' not in pr.report(0, sessions=[])

def test_subagent_runs_read_only_the_first_user_line(tmp_path):
    f = tmp_path/'proj'/'subagents'/'agent-1.jsonl'; f.parent.mkdir(parents=True)
    f.write_text('{"type": "system"}\n{"type": "user", "message": {"role": "user", "content": "Find the old tests"}}\n{"type": "user", "message": {"content": "later"}}\n')
    [r] = pr.subagent_runs(0, tmp_path)
    assert r['first'] == 'Find the old tests' and r['size'] == f.stat().st_size and r['at'] == f.stat().st_mtime
    assert pr.subagent_runs(0, tmp_path/'none') == [] and pr.subagent_runs(f.stat().st_mtime + 1, tmp_path) == []

def test_report_with_nothing_still_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    assert 'No thread in this time.' in pr.report(0, sessions=[])
    assert 'No thread in this time.' in pr.report(0, sessions=[dict(first='x', at=1., size=1, path='p')])

def test_diff_flags_xfail_and_skip(tmp_path):
    git = lambda *a: subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], capture_output=True, text=True, check=True).stdout
    git('init', '-q'); (tmp_path/'t.py').write_text('def test_a(): pass\n'); git('add', '.'); git('commit', '-qm', 'base')
    assert pr.diff_flags(tmp_path, 0) == []
    (tmp_path/'t.py').write_text('import pytest\n@pytest.mark.xfail\ndef test_a(): pytest.skip("x")\nx = 1  # noqa\ny: int = "a"  # type: ignore\n'); git('commit', '-qam', 'turn it off')
    (tmp_path/'u.py').write_text('@pytest.mark.skip\n'); git('add', '.')
    got = pr.diff_flags(tmp_path, 0)
    assert [(f['file'], f['line']) for f in got] == [('t.py', '@pytest.mark.xfail'), ('t.py', 'def test_a(): pytest.skip("x")'), ('t.py', 'x = 1  # noqa'), ('t.py', 'y: int = "a"  # type: ignore'), ('u.py', '@pytest.mark.skip')]
    assert [f['file'] for f in pr.diff_flags(tmp_path, time.time() + 3600)] == ['u.py'], 'commits older than since are left out; the working tree stays'

def test_report_shows_diff_flags_as_rows(peers, tmp_path, monkeypatch):
    monkeypatch.setattr(pr, 'diff_flags', lambda folder, since: [dict(file='t.py', line='@pytest.mark.xfail')])
    log(peers, env('f1', 'ask', A, B['key'], 'Fix t', at=200)); log(peers, env('f2', 'reply', dict(B, folders=[str(tmp_path/'repo')]), A['key'], 'Done', 'f1', at=201, hops=1))
    out = pr.report(0, sessions=[])
    assert '## Checks switched off in the diff' in out and '| repo | t.py | @pytest.mark.xfail |' in out

def test_thread_without_reviewer_is_flagged():
    t = lambda proof: dict(proof=proof)
    assert pr.proof_reviewer(t(['pytest: 12 passed'])) == 'no reviewer in the proof'
    assert pr.proof_reviewer(t(['pytest: 12 passed', 'reviewed by Leela: approved'])) == ''
    assert pr.proof_reviewer(t([])) == '', 'no proof is a different flag: not proven'
    ts = pr.threads(ROWS)
    assert any('review' in a and 'Add the tell shortcut' in a for a in pr._reviews(ts))
