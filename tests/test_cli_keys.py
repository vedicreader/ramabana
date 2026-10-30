"Extended keys: kitty and modifyOtherKeys decode to teleprint's names, shift+enter starts a line, shift+tab cycles approvals."
import asyncio, os, select, sys, threading, time

import pytest
from teleprint.compositor import Compositor
from teleprint.keys import CPR, Key, Paste, Parser
from teleprint.tty import RealTty

from ramabana.cli import KEYS_OFF, KEYS_ON
from ramabana.testing import fake_agent


def _names(*chunks):
    "Key names out of one parser fed `chunks` as separate reads."
    p = Parser()
    return [e.name if isinstance(e, Key) else e for c in chunks for e in p.feed(c)]


KITTY = {'\x1b[57414u': 'enter', '\x1b[57399u': '0', '\x1b[57408u': '9', '\x1b[57409u': '.', '\x1b[57413u': '+',
         '\x1b[57417u': 'left', '\x1b[57420u': 'down', '\x1b[57421u': 'pageup', '\x1b[57426u': 'delete', '\x1b[57414;5u': 'ctrl+enter',
         '\x1b[127;2u': 'backspace', '\x1b[32;2u': ' ', '\x1b[106;5u': 'enter', '\x1b[109;5u': 'enter', '\x1b[105;5u': 'tab',
         '\x1b[27;2;127~': 'backspace', '\x1b[27;5;106~': 'enter',
         '\x1b[13u': 'enter', '\x1b[13;2u': 'shift+enter', '\x1b[13;3u': 'alt+enter', '\x1b[9u': 'tab',
         '\x1b[9;2u': 'shift+tab', '\x1b[27u': 'escape', '\x1b[127u': 'backspace', '\x1b[99;5u': 'ctrl+c',
         '\x1b[100;5u': 'ctrl+d', '\x1b[103;5u': 'ctrl+g', '\x1b[111;5u': 'ctrl+o', '\x1b[116;5u': 'ctrl+t',
         '\x1b[114;5u': 'ctrl+r', '\x1b[112;5u': 'ctrl+p', '\x1b[110;5u': 'ctrl+n', '\x1b[121;5u': 'ctrl+y',
         '\x1b[49;3u': 'alt+1', '\x1b[57;3u': 'alt+9', '\x1b[102;3u': 'alt+f', '\x1b[32;5u': 'ctrl+space',
         '\x1b[97u': 'a', '\x1b[13;2:1u': 'shift+enter', '\x1b[13;2:2u': 'shift+enter', '\x1b[99;69u': 'ctrl+c', '\x1b[108;5u': 'ctrl+l'}
XTERM = {'\x1b[27;2;13~': 'shift+enter', '\x1b[27;3;13~': 'alt+enter', '\x1b[27;5;99~': 'ctrl+c',
         '\x1b[27;2;9~': 'shift+tab', '\x1b[27;3;49~': 'alt+1', '\x1b[27;5;103~': 'ctrl+g', '\x1b[27;5;100~': 'ctrl+d', '\x1b[27;5;108~': 'ctrl+l'}
LEGACY = {'\r': 'enter', '\t': 'tab', '\x1b[Z': 'shift+tab', '\x03': 'ctrl+c', '\x04': 'ctrl+d', '\x07': 'ctrl+g', '\x0c': 'ctrl+l',
          '\x1b1': 'alt+1', '\x1b\r': 'alt+enter', '\x1b[A': 'up', '\x1b[1;5A': 'ctrl+up', '\x1b[1;3A': 'alt+up', '\x1b[3~': 'delete',
          '\x1b[5;2~': 'shift+pageup', 'a': 'a', '\x7f': 'backspace'}


def test_kitty_modify_other_keys_and_legacy_forms_decode_to_the_same_names():
    for table in (KITTY, XTERM, LEGACY):
        for seq, name in table.items(): assert _names(seq) == [name], (seq, _names(seq))
    assert Parser().feed('\x1b[97u')[0].char == 'a', 'a printable is still typed'
    assert _names('\x1b[13;2:3u') == [], 'a key release is not a keystroke'
    assert _names('\x1b[57441u') == [] and _names('\x1b[57428u') == [] and _names('\x1b[57427u') == [], 'modifier, media and keypad-begin keys are dropped, not typed'
    assert Parser().feed('\x1b[57399u')[0].char == '0' and Parser().feed('\x1b[32;2u')[0].char == ' '
    assert _names('\x1b[27;5;99~x') == ['ctrl+c', 'x'] and _names('\x1b[9;2uz\x1b[Z') == ['shift+tab', 'z', 'shift+tab']
    # the neighbours keep their meaning: CPR, paste, and ESC [ 27 ~ with too few params
    p = Parser()
    assert p.feed('\x1b[5;9R') == [CPR(4, 8)] and p.feed('\x1b[200~hi\x1b[201~') == [Paste('hi')]


class _Pty(RealTty):
    size = (40, 10)


def _drain(fd):
    out = b''
    while select.select([fd], [], [], .05)[0]: out += os.read(fd, 4096)
    return out.decode()


def test_a_real_tty_asks_for_extended_keys_and_gives_them_back(term):
    from teleprint.transcript import TranscriptView
    term = term()
    async def go():
        tty = _Pty()
        comp = await Compositor(tty).start()
        on = term.text()
        view = TranscriptView(comp, lambda: ([], None))
        view.enter(); view.leave()
        alt = term.text()[len(on):]
        n = len(term.text())
        async with comp.borrow(): freed = term.text()[n:]
        n += len(freed)
        back = term.text()[n:]
        comp.stop()
        off = term.text()[n + len(back):]
        tty.restore()
        return on, alt, freed, back, off
    on, alt, freed, back, off = asyncio.run(go())
    assert KEYS_ON in on and KEYS_OFF in off
    # kitty flags are per screen: pushed on the alt screen after entering it, popped before leaving it
    assert alt.index('\x1b[?1049h') < alt.index('\x1b[>1u') < alt.index('\x1b[<u') < alt.index('\x1b[?1049l')
    assert KEYS_OFF in freed and KEYS_ON in back, 'a borrower gets the terminal as the shell left it'
    assert '\x1b[?2004;1006;1000l' in freed and '\x1b[?1000;1006;2004h' in back, 'mouse reports and paste brackets are lent back too'


def test_ctrl_z_from_the_transcript_view_lends_the_main_screen_and_takes_it_back(term, monkeypatch):
    """Teleprint 0.1.4 replaced `release` and `reanchor` with `borrow`, which also puts the terminal in raw mode
    and saves the mode it found. A second ctrl+z while the first was out would save raw mode as the app's."""
    import signal, termios
    from teleprint.transcript import TranscriptView
    term, stops, held = term(), [], {}
    def kill(pid, sig):
        stops.append(sig)
        with pytest.raises(StopIteration): held['comp'].suspend().send(None)   # ctrl+z again before `fg`
    monkeypatch.setattr(os, 'kill', kill)
    async def go():
        tty = _Pty()
        comp = held['comp'] = await Compositor(tty).start()
        mode = termios.tcgetattr(tty.fd)
        view = TranscriptView(comp, lambda: ([], None))
        view.enter()
        n = len(term.text())
        await comp.suspend()
        lent, after = term.text()[n:], termios.tcgetattr(tty.fd)
        view.leave(); comp.stop(); tty.restore()
        return mode, after, lent
    mode, after, lent = asyncio.run(go())
    assert stops == [signal.SIGTSTP], stops
    assert after == mode, 'the app gets its own terminal mode back, not raw mode'
    # off the alt screen first, so the shell sees the main screen; modes and keys handed back; all taken again after
    i = [lent.index(s) for s in ('\x1b[<u', '\x1b[?1049l', '\x1b[?2004;1006;1000l', '\x1b[?1000;1006;2004h', '\x1b[6n')]
    assert i == sorted(i), (i, lent)
    assert lent.index('\x1b[?1000;1006;2004h') < lent.rindex('\x1b[?1049h') < lent.rindex('\x1b[>1u')


class _Term:
    "A pty standing in for the user's terminal: drains what the app writes and answers its cursor queries."
    def __init__(self):
        self.master, self.slave = os.openpty()
        self.files = os.fdopen(os.dup(self.slave), 'r'), os.fdopen(os.dup(self.slave), 'w')
        self.out, self.done = b'', False
        self.t = threading.Thread(target=self._pump, daemon=True); self.t.start()
    def _pump(self):
        while not self.done:
            if not select.select([self.master], [], [], .02)[0]: continue
            try: got = os.read(self.master, 4096)
            except OSError: return
            self.out += got
            for _ in range(got.count(b'\x1b[6n')): os.write(self.master, b'\x1b[1;1R')
    def text(self):
        time.sleep(.1)
        return self.out.decode(errors='replace')
    def close(self):
        self.done = True; self.t.join()
        for f in self.files: f.close()
        os.close(self.master); os.close(self.slave)


@pytest.fixture
def term(monkeypatch):
    "Call it inside the test: pytest's capture takes `sys.stdout` back between setup and the call."
    t = _Term()
    def use():
        monkeypatch.setattr(sys, 'stdin', t.files[0])
        monkeypatch.setattr(sys, 'stdout', t.files[1])
        return t
    yield use
    t.close()


def test_an_exception_before_the_loop_still_gives_the_keys_back(term, monkeypatch):
    from ramabana import cli
    term = term()
    tty = _Pty()
    monkeypatch.setattr(cli, 'AppTty', lambda: tty)
    def broken(*a, **kw): raise RuntimeError('no such session')
    monkeypatch.setattr(cli, 'Ui', broken)
    agent, _ = fake_agent()
    with pytest.raises(RuntimeError): asyncio.run(cli.amain(agent))
    out = term.text()
    assert KEYS_ON in out and out.rindex(KEYS_OFF) > out.rindex(KEYS_ON), 'the shell is left in extended-key mode'


def test_alt_o_folds_and_opens_every_tool_block_in_the_whole_transcript():
    "ctrl+o reaches the turn on screen; alt+o reaches every call, including turns already scrolled away."
    from rich.text import Text
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        old = u.say(Text('call one\nits result'), 'tool', fold=None)
        old.committed = True                      # a turn long gone into the scrollback
        new = u.say(Text('call two\nits result'), 'tool', fold=None)
        reply = u.say(Text('prose\nmore prose'), 'reply', fold=None)
        u.on_key(Key('alt+o'))
        assert old.collapsed and new.collapsed and not reply.collapsed
        u.on_key(Key('alt+o'))
        assert not old.collapsed and not new.collapsed
    try: asyncio.run(go())
    finally: tty.close()



def test_talk_aims_typed_lines_at_a_sub_agent_until_it_finishes(tmp_path, monkeypatch):
    "`/talk` sets the target by id prefix, typed lines go to its inbox, a pane mark applies as `/talk` does, and a finished target falls back to main."
    from teleprint.testing import EmuTty
    from ramabana import cli
    from ramabana.agent import _run_store
    from ramabana.pane import talk_mark
    from ramabana.runtime import Run
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    kid = Run('run_kid123', 'background', 'survey')
    _run_store(agent)[kid.id] = kid
    now = tmp_path/'now.json'
    monkeypatch.setattr(cli, '_now_file', lambda a: now)
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.buf.insert('/talk nope'); u.submit()
        assert u.target is None
        u.buf.insert('/talk run_k'); u.submit()
        assert u.target == 'run_kid123' and '→ run_kid123' in u.status().plain
        u.buf.insert('use the other file'); u.submit()
        assert kid.drain_inbox() == ['use the other file'] and u.turn is None
        talk_mark(now).write_text('main'); u.poll_talk()
        assert u.target is None and not talk_mark(now).exists() and '→' not in u.status().plain
        talk_mark(now).write_text('run_kid123'); u.poll_talk()
        assert u.target == 'run_kid123'
        kid.finish('cancelled'); u.poll_talk()
        assert u.target is None
    try: asyncio.run(go())
    finally: tty.close()


def test_the_now_snapshot_carries_the_palette_and_theme_writes_one_at_once(tmp_path, monkeypatch):
    "Each snapshot carries the active palette, so the pane paints with it; `/theme` writes the next snapshot at once, so an idle pane follows too."
    from teleprint.testing import EmuTty
    from ramabana import cli
    from ramabana.pane import read_snapshot
    tty, was = EmuTty(80, 24), cli.ACTIVE_THEME
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    now = tmp_path/'now.json'
    monkeypatch.setattr(cli, '_now_file', lambda a: now)
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent); u.loop = asyncio.get_running_loop()
        u.write_now(force=True)
        assert read_snapshot(now)['palette'] == cli.GRUVBOX
        u.buf.insert('/theme solarized-light'); u.submit()
        snap = read_snapshot(now)
        assert (snap['theme'], snap['palette']) == ('solarized-light', cli.THEMES['solarized-light'])
    try: asyncio.run(go())
    finally: tty.close(); cli.set_theme(was)


def _keys_scene(body):
    "Run `await body(ui, agent, tty)` on a live loop over an emulated 80x24 terminal."
    from teleprint.testing import EmuTty
    from ramabana.agent import Approvals
    from ramabana.cli import Ui
    from ramabana.tools import WRITE_TOOLS
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    agent.approvals = Approvals(tools=WRITE_TOOLS, host=agent.host)
    async def go():
        await comp.start()
        u = Ui(comp, agent); u.loop = asyncio.get_running_loop()
        comp.on_key = lambda k: asyncio.iscoroutine(out := u.on_key(k)) and u.start_turn(out)
        comp.on_paste, comp.on_mouse = u.paste, u.on_mouse
        try: await body(u, agent, tty)
        finally:
            if u._queued is not None: u._queued.close(); u._queued = None
            if isinstance(u.turn, asyncio.Task):
                u.turn.cancel()
                await asyncio.gather(u.turn, return_exceptions=True)
    try: asyncio.run(go())
    finally: tty.close()


async def _slow(): await asyncio.sleep(.5)


def _screen(u, tty):
    u.paint()
    return tty.term.text()


def test_the_hint_row_follows_the_composer_the_turn_and_an_approval():
    "The row under the status bar was set once at start. Each state now names its own keys, and none that xterm.js never sends."
    async def body(u, agent, tty):
        idle = _screen(u, tty)
        u.buf.insert('fix the'); typing = _screen(u, tty)
        u.buf.clear(); u.start_turn(_slow()); running = _screen(u, tty)
        u.buf.insert('later'); u.start_turn(u.on_key(Key('alt+enter'))); waiting = _screen(u, tty)
        threading.Thread(target=lambda: agent.approvals.request('create_file', {'path': '/proj/a.md', 'text': 'x'}), daemon=True).start()
        for _ in range(40):
            await asyncio.sleep(.02)
            if u.ask is not None: break
        asking = _screen(u, tty)
        u.on_key(Key('ctrl+c'))
        assert '? keys' in idle and 'enter sends' not in idle and 'ctrl+c stops' not in idle
        assert 'enter sends' in typing and '? keys' not in typing
        assert 'ctrl+c stops' in running and 'alt+enter queues' in running and '? keys' not in running
        assert 'alt+up takes them back' in waiting
        assert 'y approve' in asking and 'alt+up takes them back' not in asking
        assert all('shift+enter' not in s for s in (idle, typing, running, waiting, asking)), 'Leela never sends shift+enter'
    _keys_scene(body)


def test_a_question_mark_on_an_empty_composer_shows_the_keys_and_after_text_types_itself():
    from ramabana.cli import HELP
    async def body(u, agent, tty):
        assert u.on_key(Key('?', '?')) is None
        screen = _screen(u, tty)
        assert u.buf.text == '' and list(u.comp.blocks.values())[-1].source == HELP and 'api_call' in screen
        u.buf.insert('why'); u.on_key(Key('?', '?'))
        assert u.buf.text == 'why?'
    _keys_scene(body)


def test_the_composer_takes_newlines_and_edits_a_selection():
    "shift+enter starts a line and never sends, even mid-turn; ctrl+a, cmd+a and shift+arrows select; typing or deleting replaces the selection."
    async def body(u, agent, tty):
        comp = u.comp
        comp.on_bytes(b'one\x1b[13;2utwo')
        assert u.buf.text == 'one\ntwo' and u.turn is None and u.history == []
        u.start_turn(_slow())
        comp.on_bytes(b'\x1b[27;2;13~three')
        assert u.buf.text == 'one\ntwo\nthree' and u._queued_text == [], 'shift+enter mid-turn neither steers nor queues'
        comp.on_bytes(b'\x01z')
        assert u.buf.text == 'z', 'ctrl+a selects everything and typing replaces it'
        comp.on_bytes(b'abc\x01\x7f')
        assert u.buf.text == ''
        comp.on_bytes(b'kept\x1b[97;9u')
        assert u.buf.text == 'kept' and u.buf.selection() == (0, 4), 'cmd+a selects and types nothing'
        comp.on_bytes(b'\x1b[3~')
        assert u.buf.text == ''
        comp.on_bytes(b'abcd\x1b[1;2D\x1b[1;2DX')
        assert u.buf.text == 'abX'
        comp.on_bytes(b'\x1b[1;2D\x1b[D')
        assert u.buf.selection() is None and u.buf.cursor == 2, 'a plain move ends the selection'
        comp.on_bytes(b'\r')
        assert u.buf.text == '', 'enter still sends'
        if u.turn is not None:
            u.turn.cancel()
            await asyncio.gather(u.turn, return_exceptions=True)
        u.enter_transcript()
        u.transcript.composing = True
        comp.on_bytes(b'first\x1b[13;2usecond')
        assert u.buf.text == 'first\nsecond' and u.transcript.active
        u.buf.clear()
        u.leave_transcript()
    _keys_scene(body)


def test_a_drag_over_a_wrapped_draft_selects_by_cell_and_typing_replaces_it():
    "The mouse is the terminal's until there is a draft; a drag over wrapped, wide text selects what it covers, scrolled or not."
    from rich.cells import cell_len
    async def body(u, agent, tty):
        comp = u.comp
        for i in range(30): u.note(f'note {i}')
        u.paint()
        assert comp._modes == [2004]
        text = 'x' * 76 + ' 中文START ' + 'y' * 50 + ' END tail'
        comp.on_bytes(text.encode())
        assert {1000, 1002, 1006} <= set(comp._modes), 'a draft takes the mouse for the composer'
        lines = tty.term.text().splitlines()
        top = next(i for i, l in enumerate(lines) if l.startswith('▌ xxx'))
        second = lines[top + 1]
        assert second.startswith('中文START')
        start_col = cell_len(second[:second.index('START')])
        end_col = cell_len(second[:second.index('END')])
        def mouse(btn, x, y, fin='M'): comp.on_bytes(f'\x1b[<{btn};{x + 1};{y + 1}{fin}'.encode())
        mouse(0, 10, top)
        mouse(32, start_col, top + 1)
        assert u.buf.selection() == (8, text.index('START')), 'a wide character takes two cells'
        mouse(32, end_col, top + 1); mouse(0, end_col, top + 1, 'm')
        assert u.buf.selection() == (8, text.index('END'))
        lit = [text[s.start - 2:s.end - 2] for s in u.prompt().spans if 'reverse' in str(s.style)]
        assert ''.join(lit) == text[8:text.index('END')], 'the selection paints in reverse video'
        comp.on_bytes(b'Q')
        assert u.buf.text == 'x' * 8 + 'QEND tail' and not any(u.kind(b) == 'user' for b in comp.blocks.values())
        comp.on_bytes(b'\x03')
        assert comp._modes == [2004], 'an empty composer gives the mouse back'
    _keys_scene(body)


def test_the_wheel_browses_the_transcript_while_a_draft_holds_the_mouse():
    "A draft takes mouse reporting for dragging, which stops the terminal scrolling itself; the wheel then browses the transcript as `/mouse on` does."
    async def body(u, agent, tty):
        comp = u.comp
        for i in range(60): u.note(f'note {i}')
        comp.on_bytes(b'a draft')
        assert 1000 in comp._modes and not u.mouse and not u.transcript.active
        def wheel(btn): comp.on_bytes(f'\x1b[<{btn};5;5M'.encode())
        wheel(64)
        assert u.transcript.active and u.buf.text == 'a draft'
        entered = u.transcript.top
        wheel(64)
        up = u.transcript.top
        assert up < entered
        wheel(65)
        assert u.transcript.top > up
        u.leave_transcript()
        assert u.buf.text == 'a draft'
    _keys_scene(body)


def _draft_mouse(u, tty, text):
    "Put `text` in the composer under one note, and return the row its first line is on and a function that sends a mouse report at a cell."
    u.note('above')
    u.buf.insert(text); u.paint()
    top = next(i for i, l in enumerate(tty.term.text().splitlines()) if l.startswith('▌ a'))
    def mouse(btn, x, y, fin='M'): u.comp.on_bytes(f'\x1b[<{btn};{x + 1};{y + 1}{fin}'.encode())
    return top, mouse


def test_a_click_on_each_blank_draft_line_lands_on_that_line():
    "Consecutive blank lines between two lines of text each have their own offset."
    async def body(u, agent, tty):
        top, mouse = _draft_mouse(u, tty, 'a\n\n\nb')
        for row, offset in enumerate((0, 2, 3, 4)):
            mouse(0, 0, top + row); mouse(0, 0, top + row, 'm')
            assert u.buf.cursor == offset, (row, offset, u.buf.cursor)
    _keys_scene(body)


def test_a_click_right_of_a_draft_line_lands_after_its_last_character():
    "Past the text of a row the offset is the end of that row's last character, and a click on a character still lands before it."
    async def body(u, agent, tty):
        top, mouse = _draft_mouse(u, tty, 'abc\ndef')
        for row, x, offset in ((0, 20, 3), (1, 20, 7), (0, 4, 2)):
            mouse(0, x, top + row); mouse(0, x, top + row, 'm')
            assert u.buf.cursor == offset, (row, x, offset, u.buf.cursor)
    _keys_scene(body)


def test_a_drag_released_away_from_the_draft_is_over():
    "A release over the transcript ends the drag, so a later release over the draft does not move the selection."
    async def body(u, agent, tty):
        top, mouse = _draft_mouse(u, tty, 'a\n\n\nb')
        mouse(0, 0, top); mouse(32, 0, top + 3)
        assert u.buf.selection() == (0, 4)
        mouse(0, 0, 0, 'm')
        mouse(0, 0, top + 1, 'm')
        assert u.buf.selection() == (0, 4)
    _keys_scene(body)


def test_cli_hints_false_hides_the_hint_row(tmp_path, monkeypatch):
    cfg = tmp_path/'config.toml'
    cfg.write_text('[cli]\nhints = false\n')
    monkeypatch.setenv('RAMABANA_CONFIG', str(cfg))
    async def body(u, agent, tty):
        u.hint = 'THE FOLDERS'
        idle = _screen(u, tty)
        u.start_turn(_slow()); running = _screen(u, tty)
        assert 'THE FOLDERS' not in idle and '? keys' not in idle and 'ctrl+c stops' not in running
    _keys_scene(body)