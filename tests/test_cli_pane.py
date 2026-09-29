"The `now` pane: the Ui keeps `<runs_dir>/now.json` fresh, and `/pane` opens a tmux split that draws it."
import asyncio, os, shlex
from pathlib import Path
from types import MethodType, SimpleNamespace

import fastmux, pytest
from teleprint.compositor import Compositor
from shalya.host import LocalHost
from teleprint.testing import EmuTty

import ramabana.cli as cli
from ramabana.cli import Ui, amain, main
from ramabana.pane import read_snapshot
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


def test_the_snapshot_is_throttled_while_calls_change_and_written_idle_when_the_turn_ends(ui, clock, monkeypatch):
    wrote = []
    real = cli.write_snapshot
    monkeypatch.setattr(cli, 'write_snapshot', lambda agent, path: (wrote.append(path), real(agent, path)))
    act = ui.agent.activity.start('read_file', {'path': 'a.py'})
    ui.agent.activity.finish(act, 'ok')
    assert len(wrote) == 1, 'two changes inside 0.2s are one write'
    assert wrote[0] == ui.agent.runs_dir/'now.json'
    clock.now += cli.PANE_EVERY
    ui.agent.activity.start('grep', {'pattern': 'x'})
    assert len(wrote) == 2, 'a change after the window writes again'

    async def turn(): return await cli.run_turn(ui, 'hello')
    asyncio.run(turn())
    assert len(wrote) >= 3, 'the turn ending writes even inside the window'
    snap = read_snapshot(wrote[-1])
    assert snap['busy'] is False and snap['root']['state'] != 'running', 'and what it writes is idle'


def test_nothing_is_written_without_a_runs_dir(monkeypatch):
    u, tty = _ui(None)
    wrote = []
    monkeypatch.setattr(cli, 'write_snapshot', lambda agent, path: wrote.append(path))
    u.agent.activity.start('read_file', {'path': 'a.py'})
    u.write_now(force=True)
    assert wrote == [] and u.agent.runs_dir is None
    u.agent.host.tmux_pane = Me()
    _submit(u, '/pane')
    assert u.pane is None and u.agent.host.tmux_pane.splits == [] and 'runs' in _said(u)
    tty.close()


def test_pane_opens_once_in_a_right_split_and_off_kills_it(ui):
    me = ui.agent.host.tmux_pane = Me()
    assert _submit(ui, '/pane') is None
    path = ui.agent.runs_dir/'now.json'
    assert me.splits == [('right', cli.pane_cmd(path), '35%')], 'tmux split-window -h -l 35%'
    assert shlex.split(cli.pane_cmd(path))[-1] == str(path)
    assert ui.pane is me.made[0] and read_snapshot(path) is not None, 'the id is kept and the file is there to draw'
    _submit(ui, '/pane')
    assert len(me.splits) == 1 and 'already open' in _said(ui)
    _submit(ui, '/pane off')
    assert me.made[0].killed and ui.pane is None
    _submit(ui, '/pane off')
    assert 'no pane' in _said(ui)
    _submit(ui, '/pane')
    assert len(me.splits) == 2 and ui.pane is me.made[1], 'it opens again after off'


def test_a_pane_its_viewer_left_is_forgotten_and_opened_again(ui):
    "Ctrl+c in the viewer ends the pane without the Ui hearing of it."
    me = ui.agent.host.tmux_pane = Me()
    _submit(ui, '/pane')
    me.made[0].alive = False
    _submit(ui, '/pane')
    assert len(me.splits) == 2 and ui.pane is me.made[1], 'a dead pane is not "already open"'
    me.made[1].alive = False
    _submit(ui, '/pane off')
    assert ui.pane is None and not me.made[1].killed and 'already closed' in _said(ui)


def test_a_dead_pane_tmux_kept_is_not_open_and_is_killed_before_the_next(ui):
    "With `remain-on-exit on` a viewer that quit leaves its pane dead but present."
    me = ui.agent.host.tmux_pane = Me()
    _submit(ui, '/pane')
    me.made[0].dead = True
    _submit(ui, '/pane')
    assert me.made[0].killed and len(me.splits) == 2 and ui.pane is me.made[1], 'the dead one goes, a live one opens'
    me.made[1].dead = True
    _submit(ui, '/pane off')
    assert me.made[1].killed and ui.pane is None and 'already closed' in _said(ui)


def _tick(ui, secs=.25):
    async def go():
        task = asyncio.ensure_future(ui.animate())
        await asyncio.sleep(secs)
        task.cancel()
    asyncio.run(go())

def test_a_pane_follows_the_session_resume_moves_now_json_to(ui):
    me = ui.agent.host.tmux_pane = Me()
    _submit(ui, '/pane')
    was = ui.agent.runs_dir/'now.json'
    ui.agent.session_id = 'agent_resumed'
    now = ui.agent.runs_dir/'now.json'
    _tick(ui)
    assert me.made[0].killed and me.splits[-1] == ('right', cli.pane_cmd(now), '35%') and ui.pane is me.made[1]
    assert now != was and read_snapshot(now) is not None, 'the new pane draws the resumed session'
    _submit(ui, '/pane')
    assert len(me.splits) == 2 and 'already open' in _said(ui)


def test_a_change_the_throttle_dropped_while_idle_is_flushed_by_the_next_tick(ui, clock, monkeypatch):
    wrote = []
    monkeypatch.setattr(cli, 'write_snapshot', lambda agent, path: wrote.append(path))
    ui.write_now(force=True)
    ui.agent.activity.start('read_file', {'path': 'a.py'})
    assert len(wrote) == 1 and ui.turn is None, 'inside the window: dropped'
    clock.now += cli.PANE_EVERY
    async def tick():
        task = asyncio.ensure_future(ui.animate())
        await asyncio.sleep(.25)
        task.cancel()
    asyncio.run(tick())
    assert len(wrote) == 2, 'the next tick writes what was dropped, with no turn running'


def test_with_tmux_turned_off_pane_says_so(ui):
    ui.agent.host._tmux = False
    _submit(ui, '/pane')
    assert '--tmux off' in _said(ui) and 'another terminal' in _said(ui)


def test_outside_tmux_pane_prints_the_command_to_run(ui):
    _submit(ui, '/pane')
    assert ui.pane is None and 'another terminal' in _said(ui)
    assert str(ui.agent.runs_dir/'now.json') in _said(ui)


def test_the_pane_command_runs_the_viewer():
    cmd = shlex.split(cli.pane_cmd('/tmp/now.json'))
    assert cmd[-1] == '/tmp/now.json'
    assert os.path.basename(cmd[0]) == 'ramabana-pane' or cmd[1:3] == ['-m', 'ramabana.pane']


def test_pane_modes_at_startup(ui):
    ui.start_pane('auto')
    assert ui.pane is None and 'tmux' not in _said(ui), 'auto outside tmux stays quiet'
    ui.start_pane('on')
    assert ui.pane is None and 'another terminal' in _said(ui), 'on outside tmux says why not'
    me = ui.agent.host.tmux_pane = Me()
    ui.start_pane('off')
    assert me.splits == []
    ui.start_pane('auto')
    assert len(me.splits) == 1 and ui.pane is me.made[0]


def test_an_unknown_pane_flag_is_refused(capsys):
    assert main(prompt='hi', pane='sideways') == 2
    assert '--pane' in capsys.readouterr().err
    assert 'pane' in cli.SURFACE_COMMANDS and '/pane' in cli.HELP


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
    monkeypatch.setattr(cli, 'RealTty', lambda: tty)
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


def test_a_snapshot_that_raises_never_escapes_write_now(ui, monkeypatch):
    def boom(agent, path): raise RuntimeError('dictionary changed size during iteration')
    monkeypatch.setattr(cli, 'write_snapshot', boom)
    ui.write_now(force=True)


def test_a_dead_viewer_is_reopened_at_most_every_ten_seconds_and_never_after_off(ui, clock):
    me = ui.agent.host.tmux_pane = Me()
    _submit(ui, '/pane')
    me.made[0].dead = True
    clock.now += cli.REOPEN_EVERY
    _tick(ui)
    assert me.made[0].killed and len(me.splits) == 2 and ui.pane is me.made[1], 'the animate tick brings it back'
    asked = me.made[1].asked
    for _ in range(5): ui._revive()
    assert me.made[1].asked == asked, 'asked tmux at most once a second'
    me.made[1].alive = False
    clock.now += 1
    ui._revive()
    assert len(me.splits) == 2, 'a viewer that keeps dying is not reopened in a loop'
    clock.now += cli.REOPEN_EVERY
    ui._revive()
    assert len(me.splits) == 3 and ui.pane is me.made[2]
    _submit(ui, '/pane off')
    clock.now += 2 * cli.REOPEN_EVERY
    ui._revive()
    assert len(me.splits) == 3 and ui.pane is None, '/pane off keeps it closed'


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
