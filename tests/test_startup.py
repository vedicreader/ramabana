"Startup: the prompt draws first, the model starts behind it, and nothing heavy loads before it has to."
import asyncio, os, subprocess, sys, textwrap, threading

SEARCH = ('litesearch', 'model2vec', 'fastlite', 'kosha', 'vishalakshi')

def child(code, timeout=120):
    "Run `code` in a fresh interpreter and return its stdout; fail with its stderr."
    r = subprocess.run([sys.executable, '-c', textwrap.dedent(code)], capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stderr[-3000:]
    return r.stdout


from teleprint.compositor import Compositor
from teleprint.testing import EmuTty
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


def test_start_imports_no_search_stack_and_starts_no_index(tmp_path):
    out = child(f'''
    import sys, threading, time
    import ramabana.agent as am
    from ramabana.testing import FakeBackend
    am.make_backend = lambda spec, **kw: FakeBackend(spec, **kw)
    a, h = am.mk_agent([{str(tmp_path)!r}], model='gpt-4.1', web=False, cfg=__import__('pathlib').Path({str(tmp_path/'cfg')!r}))
    assert a.start() is not None
    time.sleep(.5)
    print(sorted(m for m in {SEARCH!r} if m in sys.modules), [t.name for t in threading.enumerate() if 'kosha' in t.name])
    ''')
    assert out.strip() == '[] []', out


def test_library_output_goes_to_a_log_while_the_tui_owns_the_screen(tmp_path):
    """kosha's index sync draws a tqdm bar from a background thread. Written to the terminal, every
    bar landed between teleprint's frames, and each repaint of the status bar became a new line."""
    import sys, threading
    from tqdm import tqdm
    from ramabana.cli import stderr_to
    real, log = sys.stderr, tmp_path/'stderr.log'
    with stderr_to(log):
        # an earlier `sync_index` may have set TQDM_DISABLE before tqdm's import, so this bar asks to be drawn
        t = threading.Thread(target=lambda: list(tqdm(range(3), 'parse files from /proj', disable=False)))
        t.start(); t.join()
        print('a stray warning', file=sys.stderr)
    assert sys.stderr is real
    text = log.read_text()
    assert 'parse files from /proj' in text and 'a stray warning' in text


def test_a_hung_up_terminal_ends_the_read_instead_of_spinning():
    """A session whose terminal closed sat at 100% CPU: `RealTty.read` loops while `select` reports the
    dead fd readable and `os.read` returns nothing. The CLI's tty stops there and marks itself gone,
    and writing to it or restoring it no longer raises, so teardown reaches the background shells."""
    import os, pty, threading
    from ramabana.cli import AppTty
    master, slave = pty.openpty()
    t = AppTty.__new__(AppTty); t.fd, t._saved = slave, __import__('termios').tcgetattr(slave)
    os.close(master)
    got = []
    th = threading.Thread(target=lambda: got.append(t.read(timeout=0)), daemon=True)
    th.start(); th.join(2)
    assert not th.is_alive() and got == [b''] and t.gone, 'the read spun on the hung-up terminal'
    t.write('bye'); t.restore()
    os.close(slave)
