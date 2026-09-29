"Startup: the prompt draws first, the model starts behind it, and nothing heavy loads before it has to."
import asyncio, os, subprocess, sys, textwrap, threading

import pytest

SEARCH = ('litesearch', 'model2vec', 'fastlite', 'kosha', 'vishalakshi')

def child(code, timeout=120):
    "Run `code` in a fresh interpreter and return its stdout; fail with its stderr."
    r = subprocess.run([sys.executable, '-c', textwrap.dedent(code)], capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr[-3000:]
    return r.stdout

def test_building_the_prompt_and_tools_loads_no_search_stack(tmp_path):
    out = child(f'''
    import sys
    from ramabana.cli import host_kw
    from ramabana.agent import mk_agent
    a, h = mk_agent([{str(tmp_path)!r}], profile='full', web=False, host_kw=host_kw('auto'))
    assert a.system_prompt() and a.tools
    print(sorted(m for m in {SEARCH!r} if m in sys.modules))
    ''')
    assert out.strip() == '[]', out

def test_pyskills_are_listed_with_the_same_descriptions_without_importing_them():
    from shalya import skills
    from ramabana import tools
    from importlib.metadata import entry_points
    for ep in entry_points(group=skills.GROUP):
        name = ep.name.split('.')[-1] or ep.name
        ours, theirs = tools._mod_skill(name, ep.value), tools._shalya_mod_skill(name, ep.value)
        assert (ours and ours.dict()) == (theirs and theirs.dict()), ep.value
    assert skills._mod_skill is tools._mod_skill


from teleprint.compositor import Compositor
from teleprint.testing import EmuTty
import ramabana.cli as cli
from ramabana.cli import Ui
from ramabana.testing import SPEC, FakeBackend, fake_agent

class Slow(FakeBackend):
    "A backend whose start waits on `gate`, then fails when `fail`."
    def __init__(self, gate, fail=False, **kw):
        super().__init__(SPEC, **kw)
        self.gate, self.fail = gate, fail
    def _start(self):
        assert self.gate.wait(5), 'the test never opened the gate'
        if self.fail: raise RuntimeError('no weights')
        return self

def slow_agent(tmp_path, **kw):
    a, _ = fake_agent(cfg=tmp_path)
    be = Slow(threading.Event(), **kw)
    a._be = a._be_or_none = lambda job='turn': be
    return a, be

async def until(cond, secs=5):
    for _ in range(int(secs / .01)):
        if cond(): return True
        await asyncio.sleep(.01)
    return False

def session(agent, body):
    "Run `body(ui)` on a live Ui whose model starts the way `amain` starts it."
    async def go():
        comp = Compositor(EmuTty(100, 30))
        comp._register_signals = lambda: None
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        ui.begin()
        try: await body(ui)
        finally: comp.stop()
    asyncio.run(go())

def text(ui): return '\n'.join(str(b.source) for b in ui.comp.blocks.values())

def test_the_prompt_is_drawn_before_the_model_is_up(tmp_path):
    a, be = slow_agent(tmp_path)
    async def body(ui):
        await asyncio.sleep(.05)
        assert ui.starting and not a.ready
        rows, _ = ui.tail()
        assert 'starting model' in str(rows[0]) and 'working' not in str(rows[0]), rows[0]
        assert str(rows[-1]).startswith(str(ui.prompt())[:2])
        be.gate.set()
        assert await until(lambda: not ui.starting) and a.ready
        assert 'starting model' not in str(ui.tail()[0][0])
    session(a, body)

def test_a_line_sent_before_ready_waits_then_runs(tmp_path):
    a, be = slow_agent(tmp_path, replies=['hello back'])
    async def body(ui):
        await asyncio.sleep(.05)
        ui.buf.insert('hi there')
        ui.start_turn(ui.submit())
        assert ui._queued_prompt == 'hi there' and be.sent == []
        be.gate.set()
        assert await until(lambda: be.sent and ui.turn is None and ui._queued is None), be.sent
        assert 'hi there' in be.sent[-1] and 'hello back' in text(ui)
    session(a, body)

def test_a_start_that_fails_says_so_in_a_note(tmp_path):
    a, be = slow_agent(tmp_path, fail=True)
    async def body(ui):
        be.gate.set()
        assert await until(lambda: not ui.starting)
        assert 'no model available' in text(ui) and 'no weights' in text(ui), text(ui)
    session(a, body)


HEAVY = ('ramabana.core', 'ramabana.cli', 'ramabana.agent', 'rishi', 'shalya', 'teleprint', 'litesearch')

def test_the_tmux_relaunch_is_decided_before_the_heavy_imports(tmp_path):
    (bin_ := tmp_path/'bin').mkdir()
    (bin_/'tmux').write_text("#!/bin/sh\necho 'tmux 3.5a'\n"); (bin_/'tmux').chmod(0o755)
    out = child(f'''
    import io, os, sys
    os.environ['PATH'] = {str(bin_)!r} + ':' + os.environ['PATH']
    for k in ('TMUX', 'RAMABANA_TMUX', 'RAMABANA_WRAPPED', 'LEELA_TMUX', 'LEELA_WRAPPED'): os.environ.pop(k, None)
    class Tty(io.StringIO):
        def isatty(self): return True
    real = sys.stdout
    sys.stdin = sys.stdout = Tty()
    def execvpe(file, args, env):
        real.write(repr(sorted(m for m in {HEAVY!r} if m in sys.modules)) + ' ' + env['RAMABANA_WRAPPED']); real.flush()
        os._exit(0)
    os.execvpe = execvpe
    sys.argv = ['ramabana', '--root', '.', '--cfg', {str(tmp_path/'cfg')!r}]
    from ramabana.setup import run_cli
    run_cli()
    ''')
    assert out == '[] 1', out

def test_launch_args_leave_every_session_that_returns_early_to_main():
    from ramabana.setup import launch_args
    assert launch_args(['--root', 'a,b', '--profile=full', '--no-web']) == dict(cfg=None, tmux='auto')
    assert launch_args(['--cfg', '/c', '--tmux', 'on', '--pane', 'off']) == dict(cfg='/c', tmux='on')
    for argv in (['hi'], ['--root', 'a', 'hi'], ['-'], ['--json'], ['--doctor'], ['--kernels'], ['-h'], ['--python'],
                 ['--attach', 'x'], ['--agent-proxy'], ['--tmux', 'off'], ['--tmux', 'nope'], ['--pane', 'sideways'], ['--vault', 'hi']):
        assert launch_args(argv) is None, argv

def test_launch_args_know_every_option_that_takes_a_value():
    from fastcore.script import anno_parser
    from ramabana.setup import VALUED
    p = anno_parser(cli.main.__wrapped__, pos=['prompt'])
    valued = {a.option_strings[0] for a in p._actions if a.option_strings and a.nargs != 0} - {'--xtra'}
    assert valued == set(VALUED)


# fix round 1

class _Tty(__import__('io').StringIO):
    def isatty(self): return True

def test_a_missing_tmux_is_offered_once_per_start(tmp_path, monkeypatch):
    from ramabana import setup
    asked = []
    monkeypatch.setattr(setup.Setup, 'tmux', property(lambda self: None))
    monkeypatch.setattr(setup.Setup, 'installer', lambda self: ['brew', 'install', 'tmux'])
    monkeypatch.setattr(setup.Setup, '_answer', lambda self, cmd: asked.append(cmd) or '')
    monkeypatch.setattr(setup, 'LAUNCHED', False)
    for k in ('TMUX', 'RAMABANA_TMUX', 'RAMABANA_WRAPPED', 'LEELA_TMUX', 'LEELA_WRAPPED'): monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sys, 'stdin', _Tty()); monkeypatch.setattr(sys, 'stdout', _Tty())
    def stop(*a, **kw): raise KeyError('stopped before the agent')
    monkeypatch.setattr(cli, 'mk_agent', stop)
    monkeypatch.setattr(sys, 'argv', ['ramabana', '--root', str(tmp_path), '--cfg', str(tmp_path/'cfg')])
    assert setup.run_cli() == 2
    assert len(asked) == 1, asked

def test_quitting_during_start_returns_at_once_and_closes_what_start_made(tmp_path):
    import time
    a, be = slow_agent(tmp_path)
    synced, closed = [], []
    a.host.sync_index = lambda: synced.append(1)
    chat, gated = __import__('types').SimpleNamespace(close=lambda: closed.append(1)), be._start
    be._start = lambda: (gated(), chat)[1]   # the engine a start makes after the session quit
    t0 = time.monotonic()
    async def body(ui):
        await asyncio.sleep(.05)
        ui.closed = True
        a.close()
    session(a, body)
    assert time.monotonic() - t0 < 2, 'quit waited for the start'
    be.gate.set()
    for _ in range(200):
        if closed: break
        time.sleep(.01)
    assert closed and not synced
    assert all(t.daemon for t in threading.enumerate() if t.name == 'ramabana-start')

def test_the_registry_is_built_once_when_two_threads_ask(tmp_path, monkeypatch):
    import time
    from ramabana import agent as agent_mod
    from ramabana.testing import MemHost
    calls = []
    def load(reg, *a):
        calls.append(1); time.sleep(.1); reg.mark_loaded(reg.mark())
    monkeypatch.setattr(agent_mod, 'load', load)
    a = agent_mod.Agent(MemHost({'/proj/a.py': 'x = 1\n'}), cfg=tmp_path, extensions=True, profile='full')
    ts = [threading.Thread(target=lambda: a.registry) for _ in range(2)]
    for t in ts: t.start()
    for t in ts: t.join(5)
    assert len(calls) == 1

@pytest.mark.parametrize('argv', [['--warm', '--no-warm'], ['--pii', 'redact'], ['--profile', 'huge'], ['--pii', 'maybe', '--vault'],
                                  ['--model'], ['--model', '--root', 'x'], ['--vault', '--python']])
def test_launch_args_leave_what_main_refuses_to_main(argv):
    from ramabana.setup import launch_args
    assert launch_args(argv) is None

def test_main_and_setup_refuse_with_one_check():
    import inspect
    from ramabana.setup import refusal
    assert 'refusal(' in inspect.getsource(cli.main.__wrapped__)
    assert refusal(warm=True, no_warm=True).startswith('--warm and --no-warm') and refusal() == ''
    assert refusal(pii='redact').endswith('add --vault') and 'unknown --profile' in refusal(profile='huge')

def test_early_and_the_flags_launch_args_reads_are_main_options():
    from fastcore.script import anno_parser
    from ramabana.setup import EARLY, FLAGS
    opts = {o for a in anno_parser(cli.main.__wrapped__, pos=['prompt'])._actions for o in a.option_strings}
    assert set(EARLY) <= opts and set(FLAGS) <= opts
    assert {'--json', '--doctor', '--kernels', '--python', '--attach', '--agent-proxy', '--help'} <= set(EARLY)

def test_an_index_that_fails_to_start_is_a_note_and_the_model_stays_up(tmp_path):
    a, be = slow_agent(tmp_path)
    def boom(): raise RuntimeError('kosha broke')
    a.host.sync_index = boom
    async def body(ui):
        be.gate.set()
        assert await until(lambda: not ui.starting)
        await asyncio.sleep(.05)
        assert a.ready and 'no model available' not in text(ui) and 'kosha broke' in text(ui), text(ui)
    session(a, body)

def test_ctrl_c_during_start_says_the_model_is_still_starting(tmp_path):
    a, be = slow_agent(tmp_path)
    async def body(ui):
        await asyncio.sleep(.05)
        ui.stop()
        assert 'still starting' in text(ui) and 'idle' not in text(ui), text(ui)
        be.gate.set()
        assert await until(lambda: not ui.starting)
    session(a, body)

def test_a_renamed_shalya_helper_cannot_break_import():
    out = child('''
    import shalya.skills
    orig = shalya.skills._mod_skill
    del shalya.skills._describe
    import ramabana.tools
    print(shalya.skills._mod_skill is orig)
    ''')
    assert out.strip() == 'True', out
