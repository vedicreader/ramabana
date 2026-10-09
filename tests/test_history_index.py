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


def test_a_log_that_grew_out_of_band_is_caught_up_from_the_indexed_end(tmp_path, monkeypatch):
    "Another writer appended; the tail is read, not the log, and the result matches a full rebuild."
    from ramabana.agent import _set_session_meta
    a, _ = fake_agent(cfg=tmp_path)
    head = [turn('s1', 'one', at=1)] + [dict(turn(None, 'u1', at=2), session=None), turn('s2', 'two', at=3)]
    write(a, head)
    _set_session_meta(a, 'late', title='titled before it spoke')
    size = a.history_path.stat().st_size
    tail = [dict(turn(None, 'u2', at=4), session=None), turn('s1', 'three', at=5), turn('late', 'at last', at=6),
            dict(turn(None, 'u3', at=6 + LEGACY_GAP + 1), session=None)]
    with a.history_path.open('a') as f: f.write(''.join(json.dumps(r) + '\n' for r in tail))
    import ramabana.agent as ra
    seen, orig = [], ra._index_from_log
    monkeypatch.setattr(ra, '_index_from_log', lambda p, offset=0, *a_: seen.append(offset) or orig(p, offset, *a_))
    caught = a.rebuild_index()
    assert seen == [size], 'read from the indexed end only'
    monkeypatch.setattr(ra, '_index_from_log', orig)
    full = a.rebuild_index(force=True)
    pick = lambda rows: {s: {k: r.get(k) for k in ra._INDEX_KEYS} for s, r in rows.items() if r.get('turns')}
    assert pick(caught) == pick(full)
    assert caught['late']['title'] == 'titled before it spoke' and caught['s1']['turns'] == 2
    assert [t['prompt'] for t in a.session_turns('legacy-1')] == ['u1', 'u2']
    assert [t['prompt'] for t in a.session_turns('legacy-2')] == ['u3']


def test_a_line_still_being_written_is_left_for_the_next_catch_up(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    write(a, [turn('s1', 'one', at=1)])
    line = json.dumps(turn('s1', 'two', at=2))
    with a.history_path.open('a') as f: f.write(line[:10])
    assert a.rebuild_index()['s1']['turns'] == 1
    with a.history_path.open('a') as f: f.write(line[10:] + '\n')
    assert a.rebuild_index()['s1']['turns'] == 2
    assert [t['prompt'] for t in a.session_turns('s1')] == ['one', 'two']


def test_a_turn_after_an_untagged_line_is_indexed_with_the_line_before_it(tmp_path):
    "`_index_turn` skips untagged turns; the next tagged one used to jump the index past them."
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    list(a.stream('first'))
    with a.history_path.open('a') as f: f.write(json.dumps(dict(turn(None, 'untagged', at=1), session=None)) + '\n')
    list(a.stream('second'))
    rows = a.rebuild_index()
    assert rows['s1']['turns'] == 2 and rows['legacy-1']['turns'] == 1
    assert [t['prompt'] for t in a.session_turns('legacy-1')] == ['untagged']
