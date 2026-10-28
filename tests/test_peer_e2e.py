"The whole path: a Claude session and a Ramabana session work together, hit the hop limit, and the report shows both."
import json, os, tempfile, time
from pathlib import Path

import pytest

import ramabana.control as control
import ramabana.peer_report as pr
from ramabana.control import Control, control_call
from ramabana.peer_hooks import peer_hook
from ramabana.peers import HOP_MAX, TOGETHER_HOURS, me, peers_dir, read_log, register, tell, together_on
from ramabana.testing import fake_agent

REPLY = 'Card part added.\nchanges: rupaka/card.py\nproof: pytest -q: 3 passed'


def _until(cond, what, n=200):
    for _ in range(n):
        if (got := cond()): return got
        time.sleep(.05)
    raise AssertionError(f'timed out waiting for {what}')


def test_two_sessions_work_together_and_report(monkeypatch):
    cfg = Path(tempfile.mkdtemp(dir='/tmp'))   # a Unix socket path must stay short
    monkeypatch.setenv('RAMABANA_PEERS', str(cfg/'peers'))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    monkeypatch.setattr(control, 'TOGETHER_CHECK', .05)
    monkeypatch.setattr(pr, 'summarise', lambda ts, agent=None: ('- The Card part was added.', '- Read the diff: rupaka/card.py'))
    d = peers_dir(cfg)
    register(d, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    register(d, 'codex', 's2', ['/r/leela'], os.getpid())
    claude, codex = me(cfg, 's1'), me(cfg, 's2')
    agent, _ = fake_agent(cfg=cfg, replies=[REPLY])
    ctl = Control(agent).start()
    name = control_call(ctl.path, 'status')['name']
    together_on(d, 'claude-s1', [name])
    together_on(d, ctl.key, ['abhyasa'])
    together_on(d, 'codex-s2')
    try:
        assert tell(ctl.key, 'add a Card part', kind='ask', frm=claude, cfg=cfg).startswith('told')
        def stopped():
            code, out, _ = peer_hook('claude', 'stop', {'session_id': 's1', 'cwd': str(cfg), 'stop_hook_active': False}, cfg=cfg)
            return json.loads(out) if out else None
        o = _until(stopped, 'the stop hook to block')
        assert o['decision'] == 'block' and 'Card part added' in o['reason'] and 'pytest -q: 3 passed' in o['reason']

        who, i = [claude, codex], 0
        while 'hop limit' not in (said := tell(who[1-i%2]['key'], 'ping', frm=who[i%2], thread='pp', cfg=cfg)):
            i += 1
            assert i <= HOP_MAX + 1, said
        assert i == HOP_MAX - 1, 'a thread starts at hop 1, so HOP_MAX - 1 notes go before the limit'

        p = d/f'{ctl.key}.together.json'
        p.write_text(json.dumps(json.loads(p.read_text()) | dict(until=time.time() + .2)))
        _until(lambda: ctl.report, 'the report on expiry')
        text = ctl.report.read_text()
        rows = [l for l in text.splitlines() if l.startswith('| ') and '---' not in l][1:]
        assert [r.split('|')[-2].strip() for r in rows].count('replied') == 1 and any(r.endswith('| stopped |') for r in rows), text
        assert 'The Card part was added.' in text and 'pytest -q: 3 passed' in text
        assert read_log(d, 0)
    finally: ctl.close()
