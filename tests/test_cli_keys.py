"Extended keys: kitty and modifyOtherKeys decode to teleprint's names, shift+enter queues, shift+tab cycles approvals."
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
         '\x1b[97u': 'a', '\x1b[13;2:1u': 'shift+enter', '\x1b[13;2:2u': 'shift+enter', '\x1b[99;69u': 'ctrl+c'}
XTERM = {'\x1b[27;2;13~': 'shift+enter', '\x1b[27;3;13~': 'alt+enter', '\x1b[27;5;99~': 'ctrl+c',
         '\x1b[27;2;9~': 'shift+tab', '\x1b[27;3;49~': 'alt+1', '\x1b[27;5;103~': 'ctrl+g', '\x1b[27;5;100~': 'ctrl+d'}
LEGACY = {'\r': 'enter', '\t': 'tab', '\x1b[Z': 'shift+tab', '\x03': 'ctrl+c', '\x04': 'ctrl+d', '\x07': 'ctrl+g',
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
    from ramabana.cli import HELP, Ui
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
        assert 'alt+o' in HELP
        u.on_key(Key('alt+o'))
        assert old.collapsed and new.collapsed and not reply.collapsed
        u.on_key(Key('alt+o'))
        assert not old.collapsed and not new.collapsed
    try: asyncio.run(go())
    finally: tty.close()


