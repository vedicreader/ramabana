"A terminal session listens on its control socket: a peer's prompt runs through its Ui, and the user and the agent reach other live sessions with /peers, /tell, peers() and tell()."
import asyncio, os, tempfile, time
from pathlib import Path

from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

import ramabana.cli as cli
from ramabana.agent import Approvals
from ramabana.control import Control, control_call, control_path, peer_tools
from ramabana.testing import FakeBackend, MemHost, fake_agent
from ramabana.tools import WRITE_TOOLS


class Slow(FakeBackend):
    pause = .3
    def _send(self, msg, **kw):
        time.sleep(self.pause)
        return super()._send(msg, **kw)


def _slow_agent(cfg, replies, pause=.3, **kw):
    a, _ = fake_agent(cfg=cfg, **kw)
    be = Slow(replies=replies)
    be.pause = pause
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


class PipeTty(EmuTty):
    "An emulated terminal with a real fd, so `amain` can wait on its keys."
    dropped = False
    def __init__(self, *a):
        super().__init__(*a)
        self.fd, self.w = os.pipe()
        os.set_blocking(self.fd, False)
    def read(self, timeout=None):
        try: more = os.read(self.fd, 4096)
        except BlockingIOError: more = b''
        return super().read() + more


def _cfg(): return Path(tempfile.mkdtemp(dir='/tmp'))   # a Unix socket path must stay short


async def _call(path, method, **kw):
    "`control_call` from another thread, as a peer process would make it, bounded so a failure cannot hang the suite."
    return await asyncio.wait_for(asyncio.to_thread(control_call, path, method, timeout=5, **kw), 10)


async def _until(cond, what, n=200):
    for _ in range(n):
        if cond(): return
        await asyncio.sleep(.05)
    raise AssertionError(f'timed out waiting for {what}')


def _said(u): return '\n'.join(u.transcript.block_text(b) for b in u.comp.blocks.values())


def _live(body, agent):
    "Run `await body(ui)` on a live loop over an emulated terminal."
    tty = EmuTty(100, 30)
    comp = Compositor(tty); comp._register_signals = lambda: None
    async def go():
        await comp.start()
        await asyncio.wait_for(body(cli.Ui(comp, agent, loop=asyncio.get_running_loop())), 30)
    try: asyncio.run(go())
    finally: tty.close()


def test_a_peer_prompt_runs_through_the_ui_and_a_second_waits_its_turn():
    agent, be = _slow_agent(_cfg(), ['first reply', 'second reply', 'never shown'], pause=1)
    async def body(u):
        ctl = cli.start_control(u)
        try:
            assert await _call(ctl.path, 'prompt', text='from a peer') == {'started': True}
            st = await _call(ctl.path, 'status')
            assert st['running'] and st['state'] == 'working', st
            assert 'queued' in await _call(ctl.path, 'prompt', text='one more thing')
            assert u._queued is not None, 'held by the Ui like a typed line'
            await _until(lambda: u.turn is None and u._queued is None and len(be.sent) == 2, 'both turns')
            assert 'from a peer' in str(be.sent[0]) and 'one more thing' in str(be.sent[1])
            assert 'a peer' in _said(u), 'the transcript says who sent it'
            ev = await _call(ctl.path, 'events')
            assert [e['reply'].strip() for e in ev['events'] if e['kind'] == 'turn_end'] == ['first reply', 'second reply']
            assert not (await _call(ctl.path, 'status'))['running']
            assert (await _call(ctl.path, 'prompt', text='stop me')) == {'started': True}
            for _ in range(3): assert (await _call(ctl.path, 'cancel'))['state'] in ('cancelling', 'idle')
            await _until(lambda: u.turn is None, 'the cancelled turn to end')
            assert u._stop_count == 0 and 'terminating' not in _said(u), 'a peer cancel never escalates to terminate or quit'
        finally: ctl.close()
    _live(body, agent)


def test_the_session_opens_its_socket_and_removes_it_on_exit(monkeypatch):
    tty = PipeTty(80, 24)
    monkeypatch.setattr(cli, 'AppTty', lambda: tty)
    monkeypatch.setattr(Compositor, '_register_signals', lambda self: None)
    agent = fake_agent(cfg=_cfg())[0]
    path, seen = control_path(agent), {}
    async def go():
        loop = asyncio.get_running_loop()
        async def probe():
            try:
                await _until(path.exists, 'the socket')
                seen['status'] = await _call(path, 'status')
            finally: os.write(tty.w, b'\x04')
        loop.create_task(probe())
        await asyncio.wait_for(cli.amain(agent, pane='off'), 10)
    try: asyncio.run(go())
    finally: tty.close()
    assert seen['status']['session'] == agent.session_id
    assert not path.exists(), 'the socket goes with the session'


def test_peers_and_tell_between_two_agents_in_one_process():
    d = _cfg()
    other, obe = _slow_agent(d, ['the other reply', 'after the steer'], pause=1, host=MemHost(root='/other'))
    me, _ = fake_agent(cfg=d, approvals=Approvals(tools=WRITE_TOOLS, mode='auto'))
    asked, _ = fake_agent(cfg=d, approvals=Approvals(tools=WRITE_TOOLS, mode='ask'))
    other.events_to(other.runs_dir/'events.jsonl')   # as a terminal session does
    ctls = [Control(other).start(), Control(me).start()]
    try:
        peers, tell = peer_tools(me)
        listed = peers()
        assert listed.startswith('1  other') and other.session_id in listed and me.session_id not in listed, listed
        assert 'the other reply' in tell(1, 'what are you working on?', how='prompt', wait=10)
        refused = peer_tools(asked)[1](other.session_id, 'start something', how='prompt', wait=0)
        assert 'nothing is listening' in refused and len(obe.sent) == 1, 'a prompt into another session asks first'
        control_call(control_path(other), 'prompt', text='a long job')
        time.sleep(.1)
        assert tell(other.session_id, 'turn left', wait=0).startswith('told')
        assert 'turn left' in other.run().inbox
    finally:
        for c in ctls: c.close()


def test_the_user_lists_peers_and_tells_one_by_number():
    assert '/peers' in cli.HELP and '/tell N TEXT' in cli.HELP, 'the ? card and /help name them'
    d = _cfg()
    other, obe = _slow_agent(d, ['busy'] * 3, pause=3, host=MemHost(root='/other'))
    other_ctl = Control(other).start()
    agent, be = fake_agent(cfg=d, replies=['mine'])
    async def body(u):
        ctl = cli.start_control(u)
        try:
            def typed(line):
                u.buf.text = line
                if (out := u.submit()) is not None: u.start_turn(out)
            typed('/peers')
            await _until(lambda: '1  other' in _said(u), 'the /peers list')
            assert agent.session_id not in _said(u) and other.session_id not in _said(u), 'names, never run ids'
            await _call(control_path(other), 'prompt', text='a long job')
            await asyncio.sleep(.1)
            typed('/tell 1 hello')
            await _until(lambda: 'hello' in other.run().inbox, 'the steer to reach the other session')
            typed('/tell 1')
            assert u.peer is not None and 'other' in u.status().plain
            typed('and this too')
            await _until(lambda: 'and this too' in other.run().inbox, 'the typed line to reach the target')
            assert be.sent == [], 'not run here'
            typed('/tell main')
            assert u.peer is None
            typed('back home')
            await _until(lambda: len(be.sent) == 1, 'the line to run here')
            assert 'back home' in str(be.sent[0])
            await _until(lambda: u.turn is None, 'the turn to end')
        finally: ctl.close()
    try: _live(body, agent)
    finally: other_ctl.close()
