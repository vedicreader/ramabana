"The `now` pane: the Ui keeps `<runs_dir>/now.json` fresh, and `/pane` opens a tmux split that draws it."
import asyncio, os
from pathlib import Path
from types import MethodType, SimpleNamespace

import fastmux, pytest
from teleprint.compositor import Compositor
from shalya.host import LocalHost
from teleprint.testing import EmuTty

import ramabana.cli as cli
from ramabana.cli import Ui, amain
from ramabana.testing import fake_agent


def _ui(cfg):
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    return Ui(comp, fake_agent(cfg=cfg)[0]), tty

@pytest.fixture
def ui(tmp_path):
    u, tty = _ui(tmp_path)
    yield u
    tty.close()

class Pane:
    "A tmux pane: `alive` is tmux still having it, `dead` its viewer gone while `remain-on-exit` keeps it."
    def __init__(self, id): self.id, self.killed, self.alive, self.dead, self.asked = id, False, True, False, 0
    def kill(self):
        if not self.alive: raise RuntimeError(f"can't find {self.id}")
        self.killed = True
    def refresh(self):
        self.asked += 1
        if not self.alive: raise RuntimeError(f"can't find {self.id}")
        return self

class Me:
    "This session's tmux pane: it records the splits it is asked for."
    def __init__(self): self.splits, self.made = [], []
    def split(self, where='right', cmd=None, size=None, **kw):
        self.splits.append((where, cmd, size))
        self.made.append(Pane(f'%{40 + len(self.made)}'))
        return self.made[-1]

@pytest.fixture
def clock(monkeypatch):
    "The Ui's `time.monotonic`, held still so a slow first paint cannot spend the throttle window."
    c = SimpleNamespace(now=100.0)
    monkeypatch.setattr(cli, 'time', SimpleNamespace(monotonic=lambda: c.now))
    return c

def _said(u): return ' '.join(u.transcript.block_text(b) for b in u.comp.blocks.values())

def _submit(u, line):
    u.buf.text = line
    return u.submit()


class PipeTty(EmuTty):
    "An emulated terminal with a real fd, so `amain` can wait on its keys."
    def __init__(self, *a):
        super().__init__(*a)
        self.fd, self.w = os.pipe()
        os.set_blocking(self.fd, False)
    def read(self, timeout=None):
        try: more = os.read(self.fd, 4096)
        except BlockingIOError: more = b''
        return super().read() + more


def test_the_session_opens_the_pane_in_tmux_and_quitting_closes_it(tmp_path, monkeypatch):
    tty = PipeTty(80, 24)
    monkeypatch.setattr(cli, 'AppTty', lambda: tty)
    monkeypatch.setattr(Compositor, '_register_signals', lambda self: None)
    agent = fake_agent(cfg=tmp_path)[0]
    me = agent.host.tmux_pane = Me()
    async def go():
        loop = asyncio.get_running_loop()
        loop.call_later(.5, os.write, tty.w, b'\x04')
        await asyncio.wait_for(amain(agent, pane='auto'), 10)
    asyncio.run(go())
    assert len(me.made) == 1 and me.made[0].killed, 'auto opened it inside tmux; ctrl+d took it down with the session'
    tty.close()


class BgPane(fastmux.Pane):
    "A `run_shell_bg` pane, which tmux keeps after its command exits: `code` is None while it runs."
    def __init__(self, code=None): super().__init__(id='%9', code=code, dead=code is not None, killed=False)
    def wait(self, timeout_ms=0): return self.code
    def display(self, n): return SimpleNamespace(text=f'output of {self.code}')
    def kill(self): self.killed = True

def test_the_turn_end_closes_the_panes_of_exited_shells_and_keeps_running_ones(ui, monkeypatch):
    host = ui.agent.host
    for f in ('cmd_output', 'cmd_stop', '_bg_run'): monkeypatch.setattr(host, f, MethodType(getattr(LocalHost, f), host), raising=False)
    live, done, failed = BgPane(), BgPane(0), BgPane(2)
    logged = (SimpleNamespace(poll=lambda: 0), Path('/nonexistent.log'))
    monkeypatch.setattr(host, '_bg', {'cmd_live': live, 'cmd_done': done, 'cmd_failed': failed, 'cmd_logged': logged}, raising=False)
    asyncio.run(cli.run_turn(ui, 'hello'))
    assert (live.killed, done.killed, failed.killed) == (False, True, True)
    assert host._bg['cmd_live'] is live and host._bg['cmd_logged'] is logged, 'a process without a pane is not touched'
    assert host.cmd_output('cmd_done') == ('exit 0', 'output of 0') and host.cmd_output('cmd_failed')[0] == 'exit 2', 'the output outlives the pane'


def test_a_viewer_that_keeps_dying_at_once_is_given_up_with_one_note(ui, clock):
    me = ui.agent.host.tmux_pane = Me()
    _submit(ui, '/pane')
    for _ in range(60):
        me.made[-1].alive = False   # each viewer dies within a second of opening
        clock.now += 1
        ui._revive()
    assert len(me.splits) == 3 and ui.pane is None, 'reopened twice, then given up at the third quick death'
    assert len(me.splits) == 3 and _said(ui).count('keeps exiting') == 1 and 'ramabana --doctor' in _said(ui)
    _submit(ui, '/pane')
    me.made[-1].alive = False
    clock.now += 1
    ui._revive()
    assert len(me.splits) == 5 and ui.pane is me.made[-1], '/pane starts the count again'
