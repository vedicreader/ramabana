"""A crashed turn can be resumed, a session in use is not resumed by another process, a crash keeps its
stderr, and a call that keeps returning the same result is noticed.

A session crashed in its first turn, its stderr was overwritten by the next start, and the next start's
`--resume latest` attached to another process's live conversation, so two processes wrote one run folder."""
import faulthandler, json, subprocess, sys, time
from pathlib import Path

import pytest

from ramabana.testing import fake_agent


def _dead_pid():
    p = subprocess.Popen([sys.executable, '-c', 'pass']); p.wait()
    return p.pid


def _replayed(a, sid):
    a.resume_session(sid, keep_model=True)   # the fake model's name is not a registered model
    b = a._be('turn')
    return ' '.join(m.get('content', '') for m in (b._resume_hist or b.hist or []))


def test_a_turn_cut_off_by_a_dead_process_is_recovered_and_resumed_as_interrupted(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('the one that finished'))
    a._begin_turn()                                   # a turn starts, and its process dies before the row is written
    pending = json.loads((a.runs_dir/'turn.json').read_text())
    (a.runs_dir/'turn.json').write_text(json.dumps(pending | {'prompt': 'the one that crashed', 'pid': _dead_pid()}))
    ghost = tmp_path/'runs'/'agent_20990101-000000-000000'   # a session that died in its first turn
    ghost.mkdir(parents=True)
    (ghost/'turn.json').write_text(json.dumps({'prompt': 'crashed first turn', 'at': time.time(), 'pid': _dead_pid()}))
    b, _ = fake_agent(cfg=tmp_path)
    turns = {s['id']: s['turns'] for s in b.sessions()}
    assert turns.get(a.session_id) == 2 and turns.get(ghost.name) == 1, turns
    back = _replayed(b, a.session_id)
    assert 'the one that finished' in back and 'the one that crashed' in back and 'process ended' in back, back
    assert not (a.runs_dir/'turn.json').exists() and not (ghost/'turn.json').exists()


def test_a_finished_turn_leaves_no_pending_record(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('done'))
    assert not (a.runs_dir/'turn.json').exists()


def test_recovery_survives_its_own_crash_and_never_doubles_a_turn(tmp_path):
    "A recoverer that died after renaming left its turn unseen; a turn whose row was written before its file was deleted came back twice."
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('written, file left behind'))
    row = a.history[-1]
    (a.runs_dir/'turn.json').write_text(json.dumps({'prompt': 'written, file left behind', 'pid': _dead_pid(), 'turn_id': row['turn_id']}))
    ghost = tmp_path/'runs'/'agent_20990101-000000-000001'
    ghost.mkdir(parents=True)
    (ghost/f'turn.json.{_dead_pid()}').write_text(json.dumps({'prompt': 'renamed, then its recoverer died', 'pid': _dead_pid()}))
    b, _ = fake_agent(cfg=tmp_path)
    turns = {s['id']: s['turns'] for s in b.sessions()}
    assert turns.get(a.session_id) == 1 and turns.get(ghost.name) == 1, turns


def test_a_session_held_by_a_live_process_cannot_be_claimed():
    import os
    from ramabana.agent import _claim
    holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        d = Path(__import__('tempfile').mkdtemp())
        (d/'owner.lock').write_text(str(holder.pid))
        assert _claim(d) is False
        (d/'owner.lock').write_text(str(_dead_pid()))
        assert _claim(d) is True and (d/'owner.lock').read_text() == str(os.getpid()), 'a dead holder is replaced'
    finally: holder.kill(); holder.wait()


def test_latest_skips_a_session_another_live_process_holds_and_prefers_this_folder(tmp_path):
    here, _ = fake_agent(cfg=tmp_path); list(here.stream('in /proj'))
    there, _ = fake_agent(cfg=tmp_path); list(there.stream('elsewhere, and newer'))
    from ramabana.agent import _set_session_meta
    _set_session_meta(there, there.session_id, roots=['/elsewhere'])   # a session that ran in another folder
    me, _ = fake_agent(cfg=tmp_path)
    assert me.resume_session('latest', keep_model=True)['id'] == here.session_id, 'a session from this folder comes first'
    holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        (here.runs_dir/'owner.lock').write_text(str(holder.pid))   # another live process holds it
        other, _ = fake_agent(cfg=tmp_path)
        assert other.resume_session('latest', keep_model=True)['id'] == there.session_id, 'a live session is skipped'
        with pytest.raises(RuntimeError, match='in use'): fake_agent(cfg=tmp_path)[0].resume_session(here.session_id, keep_model=True)
    finally: holder.kill(); holder.wait()


def test_stderr_is_kept_per_session_appended_and_a_hard_crash_is_traced(tmp_path):
    from ramabana.cli import stderr_log, stderr_to
    a, _ = fake_agent(cfg=tmp_path)
    log = stderr_log(a)
    assert log.parent == a.runs_dir, log
    log.parent.mkdir(parents=True, exist_ok=True); log.write_text('from an earlier start\n')
    was = faulthandler.is_enabled()
    with stderr_to(log):
        print('from this start', file=sys.stderr)
        assert faulthandler.is_enabled()
    assert log.read_text() == 'from an earlier start\nfrom this start\n'
    assert faulthandler.is_enabled() == was


def test_the_same_result_three_times_running_gets_a_note_but_changing_output_does_not():
    from ramabana.runtime import REPEAT_CALLS, Run
    from ramabana.tools import _inboxed
    grep = _inboxed(lambda pattern: 'no matches', Run('r', 'child', question='q'))
    outs = [grep('x') for _ in range(REPEAT_CALLS)]
    assert all('same result' not in o for o in outs[:-1]) and 'same result' in outs[-1], outs[-1]
    assert 'same result' not in grep('y'), 'other arguments start again'
    mixed = iter(['x', {'not': 'text'}, 'x', 'x'])
    once = _inboxed(lambda: next(mixed), Run('m', 'child', question='q'))
    assert all('same result' not in str(once()) for _ in range(4)), 'a result that is not text breaks the run of repeats'
    ticks = iter(range(100))
    poll = _inboxed(lambda: f'line {next(ticks)}', Run('p', question='q'))
    assert all('same result' not in poll() for _ in range(REPEAT_CALLS * 2)), 'output that changes is polling, not a loop'
