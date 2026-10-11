"A session is one process's at a time on every turn, and its log stays whole lines however many processes append to it."
import json, subprocess, sys, textwrap

import pytest

from ramabana import agent
from ramabana.testing import fake_agent


def test_a_turn_in_a_session_another_process_holds_is_refused_before_anything_is_written(tmp_path):
    "Only `resume_session` refused a held session; a turn went ahead and wrote into it."
    a, _ = fake_agent(cfg=tmp_path, session_id='shared')
    assert a.session_id == 'shared', 'a host names its own sessions'
    holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        lock = tmp_path/'runs'/'shared'/agent.LOCK
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(holder.pid))
        with pytest.raises(agent.SessionBusy, match=str(holder.pid)): a.ask('hello')
        assert not any(t.get('session') == 'shared' for t in a.history), 'no row in a session another process holds'
    finally:
        holder.kill(); holder.wait()
    assert isinstance(a.ask('hello'), str) and a.history[-1]['session'] == 'shared', 'free once its holder is gone'


def test_lines_appended_from_two_processes_stay_whole(tmp_path):
    "A long line reaches the file in more than one write, and another process could land between them."
    log = tmp_path/'agent-history.jsonl'
    code = textwrap.dedent('''
        import json, sys
        from ramabana.agent import _append_line
        for i in range(100): _append_line(sys.argv[1], json.dumps({"who": sys.argv[2], "i": i, "pad": "x" * 100000}) + "\\n")
    ''')
    ps = [subprocess.Popen([sys.executable, '-c', code, str(log), w]) for w in 'ab']
    for p in ps: assert p.wait(120) == 0
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert sorted((r['who'], r['i']) for r in rows) == sorted((w, i) for w in 'ab' for i in range(100))
