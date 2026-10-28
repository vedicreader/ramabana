"One peer list, `tell`, and the `peers`, `tell`, `inbox` and `together` commands."
import os, tempfile, threading, time
from pathlib import Path

import pytest

import ramabana.control as control
from ramabana.control import Control
from ramabana.peers import Envelope, all_peers, me, peers_cli, peers_dir, post, read_log, register, take, tell, together_state
from ramabana.testing import fake_agent

SELF = {'kind': 'cli', 'session': 'cli', 'key': 'cli', 'name': 'cli'}


@pytest.fixture
def world(monkeypatch):
    "A temp cfg and peers folder, and one live Ramabana session in it."
    cfg = Path(tempfile.mkdtemp(dir='/tmp'))
    monkeypatch.setenv('RAMABANA_PEERS', str(cfg/'peers'))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    agent, _ = fake_agent(cfg=cfg)
    rang = []
    monkeypatch.setattr(control, 'METHODS', (*control.METHODS, 'message'))
    monkeypatch.setattr(Control, 'do_message', lambda self, id: rang.append(id) or {'ok': True}, raising=False)
    ctl = Control(agent).start()
    yield cfg, agent, rang
    ctl.close()


def test_all_peers_merges_sockets_and_registrations(world):
    cfg, agent, _ = world
    register(peers_dir(cfg), 'claude', 's1', ['/r/abhyasa'], os.getpid())
    rows = all_peers(cfg)
    assert {r['kind'] for r in rows} == {'ramabana', 'claude'}
    ram = next(r for r in rows if r['kind'] == 'ramabana')
    assert ram['key'] == f'ramabana-{agent.session_id}' and ram['path'] and ram['folders'] is not None and 'approve' in ram
    assert [r['key'] for r in all_peers(cfg, exclude=agent.session_id)] == ['claude-s1']
    assert [r['key'] for r in all_peers(cfg, exclude='claude-s1')] == [ram['key']]


def test_tell_note_posts_and_rings(world):
    cfg, agent, rang = world
    out = tell(agent.session_id, 'new shortcut', frm=SELF, cfg=cfg)
    got = take(peers_dir(cfg), f'ramabana-{agent.session_id}')
    assert [e.text for e in got] == ['new shortcut'] and got[0].frm == SELF and 'told' in out
    assert rang == [got[0].id]


def test_tell_says_when_the_ring_failed(world, monkeypatch):
    cfg, agent, _ = world
    monkeypatch.setattr(Control, 'do_message', lambda self, id: 1/0)
    out = tell(agent.session_id, 'hi', frm=SELF, cfg=cfg)
    assert 'queued; not rung' in out and len(take(peers_dir(cfg), f'ramabana-{agent.session_id}')) == 1


def test_tell_all_takes_the_whole_text(world):
    cfg, agent, _ = world
    assert peers_cli(['tell', '--all', 'one', 'two'], cfg=cfg) == 0
    assert [e.text for e in take(peers_dir(cfg), f'ramabana-{agent.session_id}')] == ['one two']


def test_tell_ask_waits_for_reply(world):
    cfg, agent, _ = world
    d = peers_dir(cfg)
    def answer():
        while not (got := take(d, f'ramabana-{agent.session_id}')): time.sleep(.05)
        time.sleep(.2)
        post(d, 'cli', Envelope('reply', 'built it\nchanges: a.py; abc123\nproof: pytest -q', {'key': f'ramabana-{agent.session_id}'}, thread=got[0].thread))
    t = threading.Thread(target=answer); t.start()
    out = tell(agent.session_id, 'build Card?', kind='ask', frm=SELF, wait=5, cfg=cfg)
    t.join()
    assert 'built it' in out and 'a.py' in out and 'abc123' in out


def test_reply_text_is_split_into_changes_and_proof(world):
    cfg, agent, _ = world
    tell(agent.session_id, 'done\nchanges: a.py; b.py\nproof: pytest -q', kind='reply', thread='t1', frm=SELF, cfg=cfg)
    e, = take(peers_dir(cfg), f'ramabana-{agent.session_id}')
    assert (e.text, e.changes, e.proof, e.thread) == ('done', ['a.py', 'b.py'], ['pytest -q'], 't1')


def test_tell_to_dead_session_fails_fast(world):
    cfg, _, _ = world
    with pytest.raises(LookupError): tell('nope', 'hello', frm=SELF, cfg=cfg)
    assert read_log(peers_dir(cfg)) == []


def test_tell_refused_over_hops(world):
    cfg, agent, rang = world
    out = tell(agent.session_id, 'again', frm=SELF, hops=6, cfg=cfg)
    assert 'hop limit' in out and rang == []
    assert take(peers_dir(cfg), f'ramabana-{agent.session_id}') == []
    assert [r.get('event') for r in read_log(peers_dir(cfg))] == ['refused']


def test_tell_all_sends_notes_to_every_peer(world):
    cfg, agent, _ = world
    register(peers_dir(cfg), 'codex', 'c1', ['/r/x'], os.getpid())
    tell('', 'heads up', frm=SELF, everyone=True, cfg=cfg)
    d = peers_dir(cfg)
    assert [len(take(d, k)) for k in (f'ramabana-{agent.session_id}', 'codex-c1')] == [1, 1]
    with pytest.raises(ValueError): tell('', 'q?', kind='ask', frm=SELF, everyone=True, cfg=cfg)


def test_me_reads_claude_env(world, monkeypatch):
    cfg, _, _ = world
    assert me(cfg) == SELF
    register(peers_dir(cfg), 'claude', 's1', ['/r/abhyasa'], os.getpid())
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's1')
    assert me(cfg)['key'] == 'claude-s1'
    assert me(cfg, session='s1')['key'] == 'claude-s1'
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'unknown')
    assert me(cfg) == SELF


def test_cli_inbox_and_together(world, capsys):
    cfg, _, _ = world
    d = peers_dir(cfg)
    post(d, 'cli', Envelope('note', 'look at this', {'name': 'abhyasa', 'key': 'claude-s1'}))
    assert peers_cli(['inbox'], cfg=cfg) == 0
    assert 'look at this' in capsys.readouterr().out and take(d, 'cli') == []
    assert peers_cli(['together', 'on', '--until', '07:00'], cfg=cfg) == 0
    assert together_state(d, 'cli')
    assert peers_cli(['together', 'status'], cfg=cfg) == 0 and 'until' in capsys.readouterr().out
    assert peers_cli(['together', 'off'], cfg=cfg) == 0
    assert together_state(d, 'cli') is None


def test_cli_together_bad_time_is_a_short_error(world, capsys):
    cfg, _, _ = world
    assert peers_cli(['together', 'on', '--until', 'soon'], cfg=cfg) == 2
    assert 'HH:MM' in capsys.readouterr().err and together_state(peers_dir(cfg), 'cli') is None


def test_cli_together_on_shows_partner_modes(world, capsys):
    cfg, agent, _ = world
    register(peers_dir(cfg), 'claude', 's1', ['/r/abhyasa'], os.getpid())
    peers_cli(['together', 'on'], cfg=cfg)
    out = capsys.readouterr().out
    assert 'unknown' in out and 'abhyasa' in out


def test_cli_peers_and_tell(world, capsys):
    cfg, agent, _ = world
    register(peers_dir(cfg), 'claude', 's1', ['/r/abhyasa'], os.getpid())
    assert peers_cli(['peers', '--ids'], cfg=cfg) == 0
    assert 'abhyasa' in (out := capsys.readouterr().out) and 's1' in out
    assert peers_cli(['tell', 'abhyasa', 'hi there'], cfg=cfg) == 0
    assert [e.text for e in take(peers_dir(cfg), 'claude-s1')] == ['hi there']
    assert peers_cli(['tell', 'nobody', 'hi'], cfg=cfg) == 1
