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
