import asyncio
import re
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.agent import Approvals
from ramabana.cli import Ui
from ramabana.testing import fake_agent
from ramabana.tools import WRITE_TOOLS

CONTROLS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


@contextmanager
def surface(cols=40, rows=12):
    tty = EmuTty(cols, rows)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    try: yield Ui(comp, agent)
    finally: tty.close()


@pytest.fixture
def ui():
    with surface() as u: yield u


def drawn(ui, ok=lambda rows: True, timeout=2):
    "The tail's rows once `ok` holds of them: mod callbacks run off the UI thread, so a draw shows their results a moment after it asks."
    end = time.monotonic() + timeout
    while True:
        rows, _ = ui.tail()
        if ok(rows): return rows
        assert time.monotonic() < end, 'the mods never showed up'
        time.sleep(.01)


def view_after(ui, views, t):
    "The first band view made for a draw that came after `t`."
    drawn(ui, lambda rows: any(v.t > t for v in views))
    return next(v for v in views if v.t > t)


def test_status_and_vesha(ui):
    ui.agent.registry.status(lambda agent: 'mod segment')
    ui.agent.vesha = 'focus'
    row = drawn(ui, lambda rows: 'mod segment' in rows[0].plain)[0].plain
    assert 'vesha focus' in row


def test_bands_are_limited_styled_and_isolated(ui):
    reg = ui.agent.registry
    views = []
    def band(view):
        views.append(view)
        return [[('colored', 'bold red'), ('!', 'blue')], 'x' * 100, object(), 'extra']
    reg.band(band, rows=3)
    reg.band(lambda view: 1/0)
    reg.band(lambda view: ['second', 'third', 'fourth'], rows=3)
    rows = drawn(ui, lambda rows: any(row.plain == 'third' for row in rows))
    colored = next(i for i, row in enumerate(rows) if row.plain == 'colored!')
    assert colored < len(rows) - 1 and rows[colored].spans[0].style == 'bold red'
    assert cell_len(rows[colored + 1].plain) == ui.comp.cols
    assert rows[colored + 2].plain == 'second' and rows[colored + 3].plain == 'third'
    assert not any(row.plain in ('extra', 'fourth') for row in rows)
    assert views[0].rows == 3 and views[0].width == ui.comp.cols
    assert views[0].theme in ('dark', 'light') and views[0].colors in ('truecolor', '256', 'standard', 'none')


def test_mod_text_is_made_safe_to_draw():
    with surface(40, 30) as ui:
        reg = ui.agent.registry
        reg.status(lambda agent: 'seg\x1b[31m\tend\x7f\x9b')
        reg.status(lambda agent: 'rejected\nsegment')
        reg.band(lambda view: ['ab\x1b[2Jc\x00d\x7fe\x9bf', 'a\tb' + 'x' * 100,
                               [('p\x1b]0;x\x07q', 'bold'), ('\t', 'red'), ('z', 'blue')],
                               'two\nlines', 'cr\rzzcr', [('inval1d', 'not a style')], [('inval1d', 7)], 'last'], rows=8)
        rows = drawn(ui, lambda rows: any(row.plain == 'last' for row in rows))
        plains = [row.plain for row in rows]
        assert not any(CONTROLS.search(p) for p in plains)
        assert 'seg[31m end' in plains[0] and 'rejectedsegment' in plains[0]
        tabbed = ('a' + ' ' * 7 + 'b' + 'x' * 100)[:ui.comp.cols]
        assert 'ab[2Jcdef' in plains and tabbed in plains and 'p]0;xq  z' in plains
        assert 'twolines' in plains and 'crzzcr' in plains
        assert not any('inval1d' in p for p in plains)
        ui.paint()
        lines = [line.rstrip() for line in ui.comp.tty.term.text().splitlines()]
        assert 'ab[2Jcdef' in lines and tabbed in lines and 'p]0;xq  z' in lines


def test_invalid_band_rows_and_tabs_are_isolated(ui):
    reg = ui.agent.registry
    for value in (1.5, '3', None, True, 0, 51):
        reg.bands.append(SimpleNamespace(rows=value))
    reg.band(lambda view: ['\t' * 10 + 'x', 'one', 'two', 'three', 'overflow'], rows=5)
    rows = drawn(ui, lambda rows: any(row.plain == 'three' for row in rows))
    assert not any(row.plain == 'overflow' for row in rows)
    tabrow = next(row for row in rows if row.plain == ' ' * 40)
    assert len(ui.comp.console.render_lines(tabrow, pad=False)) == 1
    ui.paint()


def test_slow_mods_never_block_a_paint(ui):
    lock = threading.Lock()
    live, most = {}, {}
    calls = []
    def slow(name, out):
        def fn(*args):
            with lock:
                live[name] = live.get(name, 0) + 1; most[name] = max(most.get(name, 0), live[name])
                calls.append((name, threading.get_ident()))
            time.sleep(.2)
            with lock: live[name] -= 1
            return out
        return fn
    ui.agent.registry.status(slow('segment', 'slow segment'))
    ui.agent.registry.band(slow('band', ['slow band']))
    def paint():
        started = time.perf_counter(); ui.paint(); ui.status()
        return time.perf_counter() - started
    first = paint()
    times = []
    end = time.monotonic() + .6
    while time.monotonic() < end: times.append(paint()); time.sleep(.01)
    rows = drawn(ui, lambda rows: 'slow segment' in rows[0].plain and any(row.plain == 'slow band' for row in rows), timeout=3)
    cached = paint()
    print(f'paint ms: first {first * 1000:.2f}, while slow max {max(times) * 1000:.2f}, cached {cached * 1000:.2f}')
    assert first < .02 and max(times) < .02 and cached < .02
    assert 'slow band' in ui.comp.tty.term.text()
    assert most == {'segment': 1, 'band': 1}, 'a callback started again while it was still running'
    assert threading.get_ident() not in {ident for _, ident in calls}, 'a callback ran on the UI thread'


def test_a_hung_band_does_not_stall_the_others(ui):
    hung, ticks = threading.Event(), iter(range(10**6))
    ui.agent.registry.band(lambda view: hung.wait(10) and [])
    ui.agent.registry.band(lambda view: [f'tick {next(ticks)}'])
    try:
        first = next(r.plain for r in drawn(ui, lambda rows: any(r.plain.startswith('tick') for r in rows)) if r.plain.startswith('tick'))
        drawn(ui, lambda rows: any(r.plain.startswith('tick') and r.plain != first for r in rows))
    finally: hung.set()


def test_a_closed_surface_starts_no_callbacks(ui):
    drawn(ui, lambda rows: 'ctx' in rows[0].plain)
    calls = []
    ui.agent.registry.status(lambda agent: calls.append('segment'))
    ui.agent.registry.band(lambda view: calls.append('band') or [])
    ui.closed = True
    for _ in range(5): ui.tail(); time.sleep(.02)
    assert not calls


def test_a_finished_refresh_repaints_by_itself():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    agent.registry.band(lambda view: time.sleep(.1) or ['late band'])
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        ui.paint()
        assert 'late band' not in tty.term.text()
        await asyncio.sleep(.3)
        assert 'late band' in tty.term.text()
    try: asyncio.run(go())
    finally: tty.close()


def test_busy_since_tracks_surface(ui):
    views = []
    ui.agent.registry.band(lambda view: views.append(view) or [])
    assert view_after(ui, views, 0).busy_since is None
    ui.turn = object()
    first = view_after(ui, views, time.monotonic()).busy_since
    assert first is not None and view_after(ui, views, views[-1].t).busy_since == first
    ui.turn = None
    assert view_after(ui, views, time.monotonic()).busy_since is None


def test_notice_from_thread_is_drawn_once():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        def notify():
            owner = SimpleNamespace(name='clock')
            token = agent.registry._context.set((owner, False))
            try: agent.registry.notify('finished')
            finally: agent.registry._context.reset(token)
        thread = threading.Thread(target=notify); thread.start(); thread.join()
        await asyncio.sleep(.05)
        notices = [b for b in comp.blocks.values() if b.source == '[clock] finished']
        assert len(notices) == 1 and ui.kind(notices[0]) == 'note'
        ui.paint()
        assert len([b for b in comp.blocks.values() if b.source == '[clock] finished']) == 1
    try: asyncio.run(go())
    finally: tty.close()


def test_band_animation_cadence():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    times = []
    agent.registry.band(lambda view: times.append((view.t, view.busy)) or [])
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        task = asyncio.create_task(ui.animate())
        try:
            await asyncio.sleep(1)
            idle = [t for t, busy in times if not busy]
            assert len(idle) >= 2
            ui.turn = object()
            await asyncio.sleep(.5)
            busy = [t for t, working in times if working]
            assert len(busy) >= 3
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
    try: asyncio.run(go())
    finally: tty.close()


def test_refused_turn_is_a_notice():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    agent.registry.on('before_turn', lambda agent, prompt: 'not now')
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        ui.start_turn(ui._turn('hello'))
        for _ in range(100):
            await asyncio.sleep(.01)
            if ui.turn is None: break
        matches = [b for b in comp.blocks.values() if 'not now' in (b.source or '')]
        assert len(matches) == 1 and ui.kind(matches[0]) == 'note'
    try: asyncio.run(go())
    finally: tty.close()


RELEASE = ('Confirm release checklist', 'CHANGELOG updated? Version bumped?')


def _release_gate(keys, while_asked=lambda ui: None, setup=lambda agent: None):
    "Run a turn whose `before_turn` hook asks `RELEASE` and refuses on a no; press `keys` at the ask, and return the blocks as `(kind, text)`."
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent(replies=['shipped'], approvals=Approvals(tools=WRITE_TOOLS))
    setup(agent)
    agent.registry.on('before_turn', lambda agent, prompt: None if agent.ask_user(*RELEASE) else 'gate: release checklist not confirmed')
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        ui.start_turn(ui._turn('ship it'))
        for _ in range(300):
            await asyncio.sleep(.01)
            if ui.ask is not None: break
        assert ui.ask is not None, 'the hook never asked'
        while_asked(ui)
        for k in keys: ui.on_key(Key(k, k if len(k) == 1 else ''))
        for _ in range(300):
            await asyncio.sleep(.01)
            if ui.turn is None: break
        return [(ui.kind(b), b.source or '') for b in comp.blocks.values()]
    try: return asyncio.run(go())
    finally: tty.close()


def test_an_ask_from_a_mod_shows_its_title_and_preview_and_offers_only_yes_and_no():
    seen = {}
    def while_asked(ui):
        gate, mode, rules = ui.agent.approvals, ui.agent.approvals.mode, list(ui.agent.approvals.rules)
        seen['hint'], seen['prompt'] = ui.footer_hint(), ui._prefixed('')
        for k in ('a', 'A'): ui.on_key(Key(k, k))
        seen['kept'] = (ui.ask is not None, ui.buf.text, gate.mode == mode, gate.rules == rules)
    blocks = _release_gate(['n', 'enter'], while_asked)
    title, preview = RELEASE
    asked = next(text for kind, text in blocks if kind == 'ask')
    assert asked.startswith(title) and preview in asked, asked
    assert not any('ask user' in text for _, text in blocks), blocks
    assert 'n: REASON' in seen['hint'] and 'approve all' not in seen['hint'] and 'always allow' not in seen['hint'], seen['hint']
    assert '/a' not in seen['prompt'], seen['prompt']
    assert seen['kept'] == (True, '', True, True), seen['kept']
    assert any(text.startswith(f'⛔ asked: {title}') for kind, text in blocks if kind == 'note'), blocks


def _after_a_stopped_turn(agent):
    "The last turn was stopped, and composing the next prompt takes longer than the turn loop's first poll."
    agent._new_run('earlier').finish('cancelled')
    compose = agent.compose
    agent.compose = lambda *a, **kw: (time.sleep(.2), compose(*a, **kw))[1]


def test_a_hook_refusal_after_its_ask_is_answered_no_is_shown():
    blocks = _release_gate(['n', 'enter'], setup=_after_a_stopped_turn)
    assert any('gate: release checklist not confirmed' in text for kind, text in blocks if kind == 'note'), blocks


def test_a_refusal_stays_a_notice_when_the_next_turn_starts_before_the_chunk_is_read():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    moved_on = threading.Event()
    def stream_with(prompt, **kw):
        agent.current_turn_id = 't1'
        agent.history.append({'turn_id': 't1', 'state': 'refused'})
        yield 'refused: not now'
        agent.current_turn_id = 't2'
        agent.history.append({'turn_id': 't2', 'state': 'complete'})
        moved_on.set()
    agent.stream_with = stream_with
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        read = ui.mark_read
        def mark_read(*a, **kw):
            moved_on.wait(5)
            return read(*a, **kw)
        ui.mark_read = mark_read
        ui.start_turn(ui._turn('hello'))
        for _ in range(300):
            await asyncio.sleep(.01)
            if ui.turn is None: break
        matches = [b for b in comp.blocks.values() if 'refused: not now' in (b.source or '')]
        assert len(matches) == 1 and ui.kind(matches[0]) == 'note'
    try: asyncio.run(go())
    finally: tty.close()


def test_a_refusal_still_arrives_when_its_run_is_refused_before_the_chunk_is_sent():
    tty = EmuTty(60, 12)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    def stream_with(prompt, **kw):
        agent.current_turn_id = 't1'
        agent.history.append({'turn_id': 't1', 'state': 'refused'})
        agent._new_run(prompt).finish('refused')
        time.sleep(.3)
        yield 'refused: not now'
    agent.stream_with = stream_with
    async def go():
        await comp.start()
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        ui.start_turn(ui._turn('hello'))
        for _ in range(300):
            await asyncio.sleep(.01)
            if ui.turn is None: break
        matches = [b for b in comp.blocks.values() if 'refused: not now' in (b.source or '')]
        assert len(matches) == 1 and ui.kind(matches[0]) == 'note'
    try: asyncio.run(go())
    finally: tty.close()
