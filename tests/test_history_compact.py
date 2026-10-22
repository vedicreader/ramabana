"One-time compaction of a turn log written before pictures were logged as `[image]` and long tool results went to a details file."
import fcntl, json, os, subprocess, sys, threading, time

import pytest

from ramabana import agent
from ramabana.agent import RESUME_DETAIL, turn_prompt
from ramabana.testing import fake_agent

PNG = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 200


def act(i, detail):
    return {'id': f'act{i:09d}', 'tool': 'run_shell', 'args': {'command': 'ls'}, 'state': 'complete', 'ok': True, 'detail': detail}


def row(sid, n, prompt='hi', acts=(), **kw):
    return {'at': float(n), 'session': sid, 'turn_id': f'{sid}-t{n}', 'state': 'complete', 'model': 'm', 'prompt': prompt,
            'reply': f'reply {n}', 'activity': list(acts), **kw}


def old_log():
    return [row('s1', 1, str([PNG, 'describe this']), [act(1, 'short')]),
            row('s1', 2, 'plain', [act(2, 'x' * 5000), act(3, 'ok'), act(4, 'y' * 3000)]),
            row('s2', 3, 'other', [act(5, 'z' * 4000)]),
            row('s2', 4, 'untouched', [act(6, 'tiny')]),
            {'at': 0.5, 'prompt': 'before sessions', 'reply': 'r', 'model': 'm', 'activity': [act(7, 'w' * 2000)]}]


@pytest.fixture
def cfg(tmp_path):
    log = tmp_path/'agent-history.jsonl'
    log.write_text(''.join(json.dumps(r) + '\n' for r in old_log()))
    a, _ = fake_agent(cfg=tmp_path)
    a.rebuild_index(force=True)
    return tmp_path


def read(cfg):
    "Every session's hydrated turns, prompts as `turn_prompt` reads them and without the `details` reference compaction adds."
    a, _ = fake_agent(cfg=cfg)
    return {sid: [{k: v for k, v in t.items() if k != 'details'} | {'prompt': turn_prompt(t)} for t in a.session_turns(sid)]
            for sid in a.rebuild_index()}


def test_compaction_shrinks_the_log_and_moves_what_it_clips(cfg):
    log, before = cfg/'agent-history.jsonl', (cfg/'agent-history.jsonl').stat().st_size
    got = agent.compact_history(cfg)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert log.stat().st_size < before / 2 and (got['before'], got['after']) == (before, log.stat().st_size)
    assert rows[0]['prompt'] == '[image]\ndescribe this'
    assert all(len(a['detail']) <= RESUME_DETAIL + 40 for r in rows[:4] for a in r['activity'])
    assert rows[1]['details'] == 'agent-details/s1.jsonl' and 'details' not in rows[4], 'a row with no session has nowhere to put its results'
    assert len(rows[4]['activity'][0]['detail']) == 2000
    moved = {k: v for l in (cfg/'agent-details'/'s1.jsonl').read_text().splitlines() for k, v in json.loads(l)['details'].items()}
    assert sorted(len(v) for v in moved.values()) == [3000, 5000]
    assert (cfg/'agent-history.jsonl.pre-compact').stat().st_size == before
    assert (cfg/'agent-sessions.json.pre-compact').exists()


def test_a_row_with_nothing_to_change_keeps_its_bytes(cfg):
    log = cfg/'agent-history.jsonl'
    old = log.read_bytes().split(b'\n')
    agent.compact_history(cfg, backup=False)
    assert log.read_bytes().split(b'\n')[3] == old[3]


def test_a_row_the_writer_already_slimmed_keeps_its_bytes(cfg):
    "A result clipped to `RESUME_DETAIL` is longer than that again, by its marker, so it must not read as a long one."
    a, _ = fake_agent(cfg=cfg, session_id='s3')
    a.activity.finish(a.activity.start('run_shell', {'command': 'ls'}), 'q' * 5000)
    a._remember('hi', 'ok')
    log, details = cfg/'agent-history.jsonl', cfg/'agent-details'/'s3.jsonl'
    slim, whole = log.read_bytes().splitlines()[-1], details.read_bytes()
    assert b'details' in slim
    agent.compact_history(cfg, backup=False)
    assert log.read_bytes().splitlines()[-1] == slim and details.read_bytes() == whole


def test_hydrated_turns_are_the_same_before_and_after(cfg):
    a, _ = fake_agent(cfg=cfg)
    a.set_muted(True, 's2'); a.set_title('Mine', 's1')
    before = read(cfg)
    agent.compact_history(cfg)
    assert read(cfg) == before
    meta = fake_agent(cfg=cfg)[0].session_meta
    assert meta('s2')['muted'] and meta('s1')['title'] == 'Mine', 'the index keeps what the person set'


def test_a_session_resumes_by_id_after_compaction(cfg):
    a, _ = fake_agent(cfg=cfg)
    want = agent._as_messages(a.replayed_turns('s1'))
    agent.compact_history(cfg)
    b, _ = fake_agent(cfg=cfg)
    assert b.resume_session('s1', keep_model=True)['id'] == 's1' and b.session_id == 's1'
    assert agent._as_messages(b.replayed_turns('s1')) == want


def test_a_second_compaction_does_not_overwrite_the_first_backup(cfg):
    agent.compact_history(cfg)
    first = (cfg/'agent-history.jsonl.pre-compact').read_bytes()
    with pytest.raises(FileExistsError, match='pre-compact'): agent.compact_history(cfg)
    agent.compact_history(cfg, backup=False)
    assert (cfg/'agent-history.jsonl.pre-compact').read_bytes() == first


def hold(path, seconds):
    "Hold the log's lock for `seconds` on another thread, and return once it is held."
    ready = threading.Event()
    def run():
        with open(path, 'ab') as f:
            fcntl.flock(f, fcntl.LOCK_EX); ready.set(); time.sleep(seconds); fcntl.flock(f, fcntl.LOCK_UN)
    threading.Thread(target=run).start(); ready.wait(5)


def test_compaction_waits_for_a_writer_and_then_gives_up(cfg):
    log = cfg/'agent-history.jsonl'
    hold(log, 1)
    with pytest.raises(agent.HistoryBusy): agent.compact_history(cfg, wait=0.1)
    assert b'[b' in log.read_bytes(), 'a refusal changes nothing'
    start = time.time()
    agent.compact_history(cfg, wait=10)
    assert time.time() - start > 0.3 and b"[b'" not in log.read_bytes()


def test_a_session_another_process_holds_stops_compaction_unless_forced(cfg):
    log, before = cfg/'agent-history.jsonl', (cfg/'agent-history.jsonl').read_bytes()
    holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        lock = cfg/'runs'/'s1'/agent.LOCK
        lock.parent.mkdir(parents=True)
        lock.write_text(str(holder.pid))
        with pytest.raises(agent.HistoryBusy, match=f's1.*{holder.pid}'): agent.compact_history(cfg)
        assert log.read_bytes() == before and not (cfg/'agent-history.jsonl.pre-compact').exists()
        agent.compact_history(cfg, force=True)
        assert log.stat().st_size < len(before)
    finally:
        holder.kill(); holder.wait()


def test_a_line_waiting_on_a_replaced_log_lands_in_the_new_file(tmp_path):
    "A writer that queued on the old file would otherwise append to bytes nobody reads."
    log = tmp_path/'agent-history.jsonl'
    log.write_text('old\n')
    with open(log, 'ab') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        t = threading.Thread(target=agent._append_line, args=(log, 'late\n')); t.start()
        time.sleep(0.2)
        (tmp_path/'new').write_text('new\n'); os.replace(tmp_path/'new', log)
        fcntl.flock(f, fcntl.LOCK_UN)
    t.join(5)
    assert log.read_text() == 'new\nlate\n'


def test_a_huge_new_row_is_capped_and_reads_back_whole(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    big = 'p' * 2_000_000
    a._remember(big, 'ok')
    line = a.history_path.read_bytes().splitlines()[-1]
    row = json.loads(line)
    assert len(line) < agent.ROW_MAX and row['details'] == f'agent-details/{a.session_id}.jsonl'
    assert len(row['prompt']) < 2000 and a.history[-1]['prompt'] == big
    assert a.session_turns(a.session_id)[-1]['prompt'] == big
    assert agent.hydrate_turns(tmp_path, [row])[0]['prompt'] == big
    a._remember('small', 'ok')
    assert 'details' not in json.loads(a.history_path.read_bytes().splitlines()[-1])


def test_the_command_prints_sizes_and_refuses_what_it_does_not_know(cfg, capsys):
    from ramabana.setup import history_cli
    assert history_cli(['compact', '--cfg', str(cfg), '--no-backup']) == 0
    assert 'agent-history.jsonl' in capsys.readouterr().out
    assert not (cfg/'agent-history.jsonl.pre-compact').exists()
    assert history_cli(['squash']) == 2 and 'usage: ramabana history compact' in capsys.readouterr().err
