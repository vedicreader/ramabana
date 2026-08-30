"""Reading a turn log without reading all of it.

`_load_history` parsed the whole file and then kept the last 2000 turns. A log shared by Leela and
the CLI reaches tens of megabytes, and that ran after every turn and on every resume. The tail is
what the model's context needs; the session index is what a picker needs, and it is the only thing
that can answer for a conversation older than the tail.
"""
import json
import time

import pytest

from ramabana.agent import HISTORY_TAIL, HISTORY_TURNS, LEGACY_GAP
from ramabana.testing import fake_agent


def turn(session, prompt, at=0.0, model='gpt-mini', **kw):
    return {'at': at, 'session': session, 'prompt': prompt, 'reply': 'ok', 'model': model, **kw}


def write(a, rows):
    a.history_path.parent.mkdir(parents=True, exist_ok=True)
    a.history_path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    a.rebuild_index(force=True)
    a.refresh_history()


def test_a_log_past_the_window_loads_only_its_tail(tmp_path, monkeypatch):
    "The bound is bytes, so a fat log costs the window and not the file."
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setattr('ramabana.agent.HISTORY_TAIL', 4000)
    pad = 'x' * 500
    rows = [turn('s1', f'{i} {pad}', at=i) for i in range(200)]
    write(a, rows)
    assert 0 < len(a.history) < 200, f'{len(a.history)} turns from a log of 200'
    assert a.history[-1]['prompt'].startswith('199'), 'the tail is the newest end'
    assert all('prompt' in t for t in a.history), 'a partial first line was dropped, not parsed'


def test_a_log_inside_the_window_is_unchanged(tmp_path):
    "Whichever bound bites first wins, and a small log meets neither. This is what makes it safe."
    a, _ = fake_agent(cfg=tmp_path)
    rows = [turn('s1', f'p{i}', at=i) for i in range(5)]
    write(a, rows)
    assert [t['prompt'] for t in a.history] == [f'p{i}' for i in range(5)]


def test_the_turn_bound_still_applies(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setattr('ramabana.agent.HISTORY_TURNS', 10)
    write(a, [turn('s1', f'p{i}', at=i) for i in range(40)])
    assert len(a.history) == 10 and a.history[-1]['prompt'] == 'p39'


def test_sessions_names_a_conversation_entirely_outside_the_tail(tmp_path, monkeypatch):
    """The fault a tail read introduces on its own: `sessions` derived the list from `history`, so
    every conversation older than the window vanished from the picker."""
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setattr('ramabana.agent.HISTORY_TAIL', 2000)
    pad = 'y' * 400
    write(a, [turn('old', f'ancient {pad}', at=1)] + [turn('new', f'{i} {pad}', at=10 + i) for i in range(30)])
    assert 'old' not in {t.get('session') for t in a.history}, 'precondition: it is past the window'
    listed = {s['id']: s for s in a.sessions()}
    assert 'old' in listed and listed['old']['turns'] == 1
    assert listed['old']['title'].startswith('ancient')


def test_session_turns_reads_one_conversation_out_of_an_interleaved_log(tmp_path):
    "Leela and the CLI append to one log, so a session's lines are not contiguous."
    a, _ = fake_agent(cfg=tmp_path)
    rows = []
    for i in range(6): rows += [turn('a', f'a{i}', at=i * 2), turn('b', f'b{i}', at=i * 2 + 1)]
    write(a, rows)
    assert [t['prompt'] for t in a.session_turns('a')] == [f'a{i}' for i in range(6)]
    assert [t['prompt'] for t in a.session_turns('b')] == [f'b{i}' for i in range(6)]


def test_session_turns_answers_for_a_conversation_that_is_not_in_history(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setattr('ramabana.agent.HISTORY_TAIL', 2000)
    pad = 'z' * 400
    write(a, [turn('old', f'ancient {pad}', at=1)] + [turn('new', f'{i} {pad}', at=10 + i) for i in range(30)])
    assert a.session_turns('old')[0]['prompt'].startswith('ancient')
    assert [t['prompt'] for t in a.session_turns('old')] != [], 'read from the log, not from the tail'


def test_the_index_matches_what_a_full_parse_would_say(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    rows = [turn('s1', 'one', at=1), turn('s2', 'two', at=2), turn('s1', 'three', at=3)]
    write(a, rows)
    index = a.rebuild_index()
    whole = {}
    for r in rows: whole.setdefault(r['session'], []).append(r)
    assert {sid: row['turns'] for sid, row in index.items() if row.get('turns')} == \
           {sid: len(v) for sid, v in whole.items()}
    assert index['s1']['first_prompt'] == 'one' and index['s1']['last_at'] == 3


def test_an_index_whose_offsets_exceed_the_log_is_rebuilt_rather_than_trusted(tmp_path):
    "A rotated or replaced log leaves offsets that name bytes that are not there any more."
    a, _ = fake_agent(cfg=tmp_path)
    write(a, [turn('s1', f'p{i}', at=i) for i in range(20)])
    before = a.rebuild_index()['s1']['last_offset']
    a.history_path.write_text(json.dumps(turn('s1', 'the only one', at=99)) + '\n')
    a.refresh_history()
    row = a.rebuild_index()['s1']
    assert row['last_offset'] < before and row['turns'] == 1
    assert [t['prompt'] for t in a.session_turns('s1')] == ['the only one']


def test_a_turn_written_now_extends_the_index_without_a_rebuild(tmp_path):
    "`_remember` knows where its own line landed, so the common case never streams the log."
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    list(a.stream('first'))
    row = a.rebuild_index()['s1']
    assert row['turns'] == 1 and row['first_offset'] == 0
    assert row['last_offset'] == a.history_path.stat().st_size
    list(a.stream('second'))
    row = a.rebuild_index()['s1']
    assert row['turns'] == 2 and row['last_offset'] == a.history_path.stat().st_size
    assert [t['prompt'] for t in a.session_turns('s1')] == ['first', 'second']


def test_two_agents_sharing_one_log_each_see_the_others_conversation(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    b, _ = fake_agent(cfg=tmp_path)
    a.session_id, b.session_id = 'from-a', 'from-b'
    list(a.stream('a asks'))
    list(b.stream('b asks'))
    assert {s['id'] for s in a.sessions()} >= {'from-a', 'from-b'}
    assert {s['id'] for s in b.sessions()} >= {'from-a', 'from-b'}
    assert [t['prompt'] for t in a.session_turns('from-b')] == ['b asks']


def test_untagged_history_splits_the_way_a_frontend_splits_it(tmp_path):
    "`legacy-N` ids have to agree with Leela's `history_sessions`, which uses the same gap."
    a, _ = fake_agent(cfg=tmp_path)
    rows = [turn(None, 'one', at=0), turn(None, 'two', at=10),
            turn(None, 'later', at=10 + LEGACY_GAP + 1)]
    for r in rows: r.pop('session')
    write(a, rows)
    listed = {s['id']: s for s in a.sessions()}
    assert {'legacy-1', 'legacy-2'} <= set(listed)
    assert listed['legacy-1']['turns'] == 2 and listed['legacy-2']['turns'] == 1
    assert [t['prompt'] for t in a.session_turns('legacy-2')] == ['later']


def test_a_resume_of_a_conversation_outside_the_tail_keeps_its_context_and_its_roots(tmp_path, monkeypatch):
    """The trap a tail read sets. `resume_session` and `session_added_roots` both scanned
    `history`, so a resumed older conversation silently lost both."""
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setattr('ramabana.agent.HISTORY_TAIL', 2000)
    pad = 'w' * 400
    act = [{'tool': 'add_root', 'args': {'path': '/opened/here'}, 'ok': True}]
    write(a, [turn('old', f'remember cedar {pad}', activity=act, at=1)]
             + [turn('new', f'{i} {pad}', at=10 + i) for i in range(30)])
    assert 'old' not in {t.get('session') for t in a.history}, 'precondition: past the window'
    assert a.session_added_roots('old') == ['/opened/here']
    a.resume_session('old')
    back = ' '.join(m.get('content', '') for m in (a._be('turn')._resume_hist or []))
    assert 'remember cedar' in back
    assert a.resumed_roots == ['/opened/here']


def test_malformed_session_metadata_is_never_written_over_by_a_rebuild(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    write(a, [turn('s1', 'one', at=1)])
    a.sessions_path.write_text('{broken')
    before = a.sessions_path.read_text()
    assert a.rebuild_index() == {}
    assert a.sessions_path.read_text() == before and 'malformed' in a.history_problem
