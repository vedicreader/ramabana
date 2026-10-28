"A Ramabana session takes notes, asks and replies from peers: a note joins the turn, an ask asks the user or runs in work together mode, and the reply goes back."
import asyncio, os, tempfile, threading, time
from pathlib import Path

import pytest
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

import ramabana.cli as cli
import ramabana.control as control
from ramabana.agent import Approvals
from ramabana.control import Control, control_call, peer_tools, self_frm
from ramabana.peers import HOP_MAX, TOGETHER_HOURS, Envelope, peers_dir, post, register, take, together_on, together_state
from ramabana.testing import FakeBackend, MemHost, fake_agent
from ramabana.tools import WRITE_TOOLS, failed

FRM = {'kind': 'claude', 'session': 's1', 'key': 'claude-s1', 'name': 'abhyasa · claude', 'folders': ['/r/abhyasa']}
REPLY = 'Card part added.\nchanges: rupaka/card.py\nproof: pytest -q: 3 passed'


@pytest.fixture
def cfg(monkeypatch):
    "A temp cfg and peers folder with one live Claude Code session, `claude-s1`, that holds `/r/abhyasa`."
    d = Path(tempfile.mkdtemp(dir='/tmp'))   # a Unix socket path must stay short
    monkeypatch.setenv('RAMABANA_PEERS', str(d/'peers'))
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    register(peers_dir(d), 'claude', 's1', ['/r/abhyasa'], os.getpid())
    return d


def _until(cond, what, n=200):
    for _ in range(n):
        if (got := cond()): return got
        time.sleep(.05)
    raise AssertionError(f'timed out waiting for {what}')


def _ring(ctl, kind, text, **kw):
    "Post a message from `claude-s1` to the session of `ctl` and ring its socket, as `ramabana tell` does."
    env = Envelope(kind, text, FRM, ctl.key, **kw)
    post(ctl.d, ctl.key, env)
    assert control_call(ctl.path, 'message', id=env.id) == {'took': 1}
    return env


def _reply(d):
    "The one message `claude-s1` gets back."
    [r] = _until(lambda: take(peers_dir(d), 'claude-s1'), 'a reply')
    return r


def _pending(ctl): return [e.id for e in ctl._held()]


class Slow(FakeBackend):
    def _send(self, msg, **kw):
        time.sleep(1)
        return super()._send(msg, **kw)


def test_note_while_idle_joins_next_turn(cfg):
    agent, be = fake_agent(cfg=cfg, replies=['noted'])
    ctl = Control(agent).start()
    try:
        _ring(ctl, 'note', 'the Card API moved to v2')
        _until(lambda: agent.peer_notes, 'the note to be kept')
        agent.ask('go on')
        sent = str(be.sent[0])
        assert '<peer-messages>' in sent and 'the Card API moved to v2' in sent and 'from="abhyasa · claude"' in sent, sent
        assert agent.peer_notes == [] and agent.peer_notice() == '', 'a note joins one turn only'
    finally: ctl.close()


def test_note_while_running_steers(cfg):
    agent, _ = fake_agent(cfg=cfg)
    be = Slow(replies=['done'])
    agent._be = agent._be_or_none = lambda job='turn': be
    ctl = Control(agent).start()
    try:
        ctl.do_prompt('a long job')
        _until(lambda: agent.run() is not None and not agent.run().terminal, 'the turn to start')
        _ring(ctl, 'note', 'turn left')
        _until(lambda: any('turn left' in m for m in agent.run().inbox), 'the steer')
        assert agent.peer_notes == []
    finally: ctl.close()


def test_ask_needs_approval_by_default(cfg):
    ap = Approvals(tools=WRITE_TOOLS, mode='ask')
    agent, be = fake_agent(cfg=cfg, approvals=ap, replies=['never'])
    seen = []
    ap.listen(seen.append)
    ctl = Control(agent).start()
    try:
        env = _ring(ctl, 'ask', 'add a Card part', repo='leela')
        [a] = _until(lambda: seen, 'the approval')
        assert a.tool == 'peer ask' and a.args == {'from': 'abhyasa · claude', 'repo': 'leela', 'text': 'add a Card part'}
        assert _pending(ctl) == [env.id], 'kept on disk while it waits'
        ap.answer(a.id, False, 'not now')
        r = _reply(cfg)
        assert (r.kind, r.text, r.thread, r.frm['key'], r.to) == ('reply', 'refused: not now', env.thread, ctl.key, 'claude-s1')
        assert be.sent == [] and _pending(ctl) == []
    finally: ctl.close()


def test_ask_in_together_mode_starts_turn_and_replies(cfg):
    agent, be = fake_agent(cfg=cfg, replies=[REPLY])
    ctl = Control(agent).start()
    together_on(ctl.d, ctl.key)
    try:
        env = _ring(ctl, 'ask', 'add a Card part', repo='leela')
        r = _reply(cfg)
        assert (r.kind, r.thread, r.hops) == ('reply', env.thread, 1)
        assert (r.text, r.changes, r.proof) == ('Card part added.', ['rupaka/card.py'], ['pytest -q: 3 passed'])
        assert r.frm == self_frm(agent) and set(r.frm) >= {'key', 'folders'}
        sent = str(be.sent[0])
        assert 'kind="ask"' in sent and 'add a Card part' in sent and 'peer-work' in sent and 'proof:' in sent, sent
    finally: ctl.close()


def test_ask_from_non_partner_still_asks(cfg):
    ap = Approvals(tools=WRITE_TOOLS, mode='ask')
    agent, be = fake_agent(cfg=cfg, approvals=ap, replies=[REPLY])
    seen = []
    ap.listen(seen.append)
    ctl = Control(agent).start()
    together_on(ctl.d, ctl.key, partners=['leela'])
    try:
        _ring(ctl, 'ask', 'add a Card part')
        [a] = _until(lambda: seen, 'the approval')
        ap.answer(a.id, True)
        assert _reply(cfg).proof == ['pytest -q: 3 passed'], 'a yes runs the turn, and the reply goes back'
        assert len(be.sent) == 1
    finally: ctl.close()


def test_pending_ask_survives_restart(cfg):
    ap = Approvals(tools=WRITE_TOOLS, mode='ask')
    agent, _ = fake_agent(cfg=cfg, approvals=ap)
    seen = []
    ap.listen(seen.append)
    ctl = Control(agent).start()
    env = _ring(ctl, 'ask', 'add a Card part')
    _until(lambda: seen, 'the approval')
    ctl.close(); ap.close()   # the session quits before the user answers
    time.sleep(.2)
    assert _pending(ctl) == [env.id] and take(peers_dir(cfg), 'claude-s1') == [], 'a session that quits neither refuses nor forgets it'
    ap2 = Approvals(tools=WRITE_TOOLS, mode='ask')
    again, _ = fake_agent(cfg=cfg, approvals=ap2, session_id=agent.session_id)
    seen2 = []
    ap2.listen(seen2.append)
    ctl2 = Control(again).start()
    try:
        [a] = _until(lambda: seen2, 'the ask raised again')
        assert a.args['text'] == 'add a Card part'
        ap2.answer(a.id, False, 'later')
        assert _reply(cfg).text == 'refused: later' and _pending(ctl2) == []
    finally: ctl2.close()


def test_guard_refuses_other_sessions_folder(cfg):
    agent, _ = fake_agent(cfg=cfg, host=MemHost({'/r/abhyasa/a.py': 'x = 1\n'}, root='/mine'))
    out = {f.__name__: f for f in agent.tools}['replace_text']('/r/abhyasa/a.py', [{'oldText': 'x = 1', 'newText': 'x = 2'}])
    assert failed(out) and 'abhyasa · claude' in out and '/r/abhyasa/a.py' in out, out
    shared, _ = fake_agent(cfg=cfg, host=MemHost({'/r/abhyasa/a.py': 'x = 1\n'}, root='/r/abhyasa'))
    out = {f.__name__: f for f in shared.tools}['replace_text']('/r/abhyasa/a.py', [{'oldText': 'x = 1', 'newText': 'x = 2'}])
    assert not failed(out), 'a folder both sessions hold is open to both'


def test_tell_tool_sends_ask_envelope(cfg):
    agent, _ = fake_agent(cfg=cfg)
    ctl = Control(agent).start()
    peers, tell = peer_tools(agent)
    try:
        assert 'claude' in peers()
        assert failed(tell('s1', 'hi', kind='steer'))
        assert tell('s1', 'add a Card part', kind='ask', wait=0).startswith('told')
        [e] = take(peers_dir(cfg), 'claude-s1')
        assert (e.kind, e.text, e.to, e.frm) == ('ask', 'add a Card part', 'claude-s1', self_frm(agent))
        assert e.frm['folders'] == ['/proj'] and e.frm['key'] == ctl.key
        def answer():
            [ask] = _until(lambda: take(peers_dir(cfg), 'claude-s1'), 'the second ask')
            post(ctl.d, ctl.key, Envelope('reply', 'done', FRM, ctl.key, thread=ask.thread, proof=['pytest: ok']))
            control_call(ctl.path, 'message', id='x')   # the doorbell leaves a reply the tool waits for
        t = threading.Thread(target=answer, daemon=True)
        t.start()
        assert tell('s1', 'and a Badge part', kind='ask', wait=10) == 'done\nproof: pytest: ok'
        t.join(10)
        assert agent.peer_notes == []
    finally: ctl.close()


def test_mode_end_saves_report(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(control, 'TOGETHER_CHECK', .05)
    monkeypatch.setattr(control, 'save_report', lambda since, cfg=None, summary=None: calls.append(since) or Path('/tmp/r.md'))
    agent, _ = fake_agent(cfg=cfg)
    key = f'ramabana-{agent.session_id}'
    st = together_on(peers_dir(cfg), key, now=time.time() - TOGETHER_HOURS*3600 + .5)
    ctl = Control(agent).start()
    try:
        _until(lambda: calls, 'the report')
        time.sleep(.3)
        assert calls == [st['started']] and ctl.report == Path('/tmp/r.md'), 'once, for the mode that ended'
    finally: ctl.close()


def test_typed_line_ends_together_mode(cfg):
    agent, _ = fake_agent(cfg=cfg, replies=['hi'])
    tty = EmuTty(100, 30)
    comp = Compositor(tty); comp._register_signals = lambda: None
    said = lambda u: '\n'.join(u.transcript.block_text(b) for b in u.comp.blocks.values())
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent, loop=asyncio.get_running_loop())
        ctl = cli.start_control(u)
        try:
            together_on(ctl.d, ctl.key)
            u.buf.text = 'I am back'
            if (out := u.submit()) is not None: u.start_turn(out)
            assert together_state(ctl.d, ctl.key) is None and 'ramabana report' in said(u)
            for _ in range(200):
                if u.turn is None: break
                await asyncio.sleep(.05)
        finally: ctl.close()
    try: asyncio.run(asyncio.wait_for(go(), 30))
    finally: tty.close()


def test_peer_ask_always_asks_a_person(cfg):
    ap = Approvals(tools=WRITE_TOOLS, mode='auto')
    ap.always('peer ask', '*', glob=True)
    agent, be = fake_agent(cfg=cfg, approvals=ap, replies=['never'])
    seen = []
    ap.listen(seen.append)
    ctl = Control(agent).start()
    try:
        _ring(ctl, 'ask', 'add a Card part')
        [a] = _until(lambda: seen, 'the approval, in auto mode and with a saved allow rule')
        for mode in ('edits', 'auto', 'off'): ap.set_mode(mode)
        ap.cancel_all(run=object())
        assert a.pending and ap.waiting == [a], 'no mode switch or cancelled turn settles it'
        ap.answer(a.id, False, 'no')
        assert _reply(cfg).text == 'refused: no' and be.sent == []
    finally: ctl.close()


class Raises(FakeBackend):
    def _send(self, msg, **kw): raise RuntimeError('the model is down')

class TurnError(FakeBackend):
    def _send(self, msg, **kw):
        out = super()._send(msg, **kw)
        self.turn_error = 'rate limited'
        return out


@pytest.mark.parametrize('be,why', [(Raises(), 'the model is down'), (TurnError(replies=['rate limited']), 'rate limited')])
def test_failed_ask_turn_replies_failed(cfg, be, why):
    agent, _ = fake_agent(cfg=cfg)
    agent._be = agent._be_or_none = lambda job='turn': be
    ctl = Control(agent).start()
    together_on(ctl.d, ctl.key)
    try:
        env = _ring(ctl, 'ask', 'add a Card part')
        r = _reply(cfg)
        assert r.text.startswith('failed:') and why in r.text and r.thread == env.thread, r.text
    finally: ctl.close()


def test_cancelled_ask_gets_failed_reply(cfg):
    agent, _ = fake_agent(cfg=cfg)
    agent._be = agent._be_or_none = lambda job='turn': Slow(replies=['done'] * 3)
    ctl = Control(agent).start()
    together_on(ctl.d, ctl.key)
    try:
        ctl.do_prompt('a long job')
        _until(lambda: agent.run() is not None and not agent.run().terminal, 'the turn to start')
        env = _ring(ctl, 'ask', 'add a Card part')
        _until(lambda: agent.queued, 'the ask to queue')
        ctl.do_cancel()
        r = _reply(cfg)
        assert (r.text, r.thread) == ('failed: cancelled by the user', env.thread)
    finally: ctl.close()


def test_queued_asks_each_get_a_reply(cfg):
    agent, _ = fake_agent(cfg=cfg)
    be = Slow(replies=['first', REPLY, REPLY])
    agent._be = agent._be_or_none = lambda job='turn': be
    tty = EmuTty(100, 30)
    comp = Compositor(tty); comp._register_signals = lambda: None
    got = []
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent, loop=asyncio.get_running_loop())
        ctl = cli.start_control(u)
        try:
            together_on(ctl.d, ctl.key)
            await asyncio.to_thread(ctl.do_prompt, 'a long job')
            envs = [await asyncio.to_thread(_ring, ctl, 'ask', t) for t in ('add a Card part', 'and a Badge part')]
            for _ in range(200):
                got.extend(take(peers_dir(cfg), 'claude-s1'))
                if len(got) >= 2: break
                await asyncio.sleep(.05)
            assert sorted(r.thread for r in got) == sorted(e.thread for e in envs), got
            assert all(r.proof == ['pytest -q: 3 passed'] for r in got)
            for _ in range(200):
                if u.turn is None: break
                await asyncio.sleep(.05)
        finally: ctl.close()
    try: asyncio.run(asyncio.wait_for(go(), 30))
    finally: tty.close()


def test_restart_in_together_mode_runs_once(cfg):
    first, _ = fake_agent(cfg=cfg)
    env = Envelope('ask', 'add a Card part', FRM, f'ramabana-{first.session_id}')
    Control(first)._hold(env)   # as a session that quit while the user had not answered
    together_on(peers_dir(cfg), f'ramabana-{first.session_id}')
    sent = []
    for _ in range(2):
        again, be = fake_agent(cfg=cfg, replies=[REPLY], session_id=first.session_id)
        ctl = Control(again).start()
        try:
            time.sleep(.5)
            sent += be.sent
        finally: ctl.close()
    assert len(sent) == 1 and Control(first)._held() == [], 'the ask ran once, on the first restart'
    assert len(take(peers_dir(cfg), 'claude-s1')) == 1


def test_limit_refusal_in_together_mode_refuses(cfg):
    ap = Approvals(tools=WRITE_TOOLS, mode='ask')
    agent, be = fake_agent(cfg=cfg, approvals=ap, replies=['never'])
    seen = []
    ap.listen(seen.append)
    ctl = Control(agent).start()
    together_on(ctl.d, ctl.key)
    try:
        env = _ring(ctl, 'ask', 'one more round', hops=HOP_MAX)
        r = _reply(cfg)
        assert r.text.startswith('refused: hop limit') and r.thread == env.thread, r.text
        time.sleep(.2)
        assert seen == [] and be.sent == [], 'no turn, and the user is not asked'
    finally: ctl.close()
