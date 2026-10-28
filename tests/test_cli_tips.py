"Tips: one grey row at the end of the working block names a key or command, changes with the turn, and never shows while you type."
import re, time
from types import SimpleNamespace

from fastcore.script import anno_parser

from ramabana import cli
from ramabana.setup import KEYS, load_config
from test_cli_keys import _keys_scene
from test_timeline import ui  # noqa: F401  (`ui` is a fixture)


def _working(u, n=1):
    "`u` in the middle of its `n`th turn."
    u.turn, u._turn_at, u.turn_no = 'a turn', time.monotonic(), n
    return u


def _tip(u): return next((r.plain for r in u.working() if r.plain.startswith('  tip: ')), None)


def test_a_running_turn_ends_its_working_rows_with_a_tip(ui):
    rows = _working(ui).working()
    assert rows[-1].plain == '  tip: ' + cli.TIPS[0]


def test_the_tip_changes_with_the_turn_and_not_with_the_clock(ui, monkeypatch):
    assert [_tip(_working(ui, n)) for n in (1, 2)] == ['  tip: ' + t for t in cli.TIPS[:2]]
    t0 = time.monotonic()
    before = _tip(ui)
    monkeypatch.setattr(time, 'monotonic', lambda: t0 + 60)
    assert _tip(ui) == before
    assert _tip(_working(ui, len(cli.TIPS) + 1)) == '  tip: ' + cli.TIPS[0]


def test_no_tip_while_the_user_types_asks_or_has_a_menu_open(ui):
    _working(ui)
    assert _tip(ui)
    ui.buf.insert('fix')
    assert _tip(ui) is None
    ui.buf.clear()
    assert _tip(ui)
    ui.ask = SimpleNamespace(summary='x')
    assert _tip(ui) is None
    ui.ask, ui.menu = None, cli.ChoiceMenu(*cli.options_for('refactor the runtime'))
    assert _tip(ui) is None
    ui.menu = None
    assert _tip(ui)


def test_no_tip_when_idle_or_calm(ui):
    assert ui.working() == []
    _working(ui).calm = True
    assert len(ui.working()) == 1 and _tip(ui) is None


def test_cli_tips_false_hides_it(tmp_path, monkeypatch):
    assert 'cli.tips' in KEYS and KEYS['cli.tips'].type is bool
    async def on(u, agent, tty): assert u.tips is True and _tip(_working(u))
    _keys_scene(on)
    cfg = tmp_path/'config.toml'
    cfg.write_text('[cli]\ntips = false\n')
    monkeypatch.setenv('RAMABANA_CONFIG', str(cfg))
    async def off(u, agent, tty): assert u.tips is False and _tip(_working(u)) is None
    _keys_scene(off)
    assert anno_parser(cli.main.__wrapped__, pos=['prompt']).parse_args(['--no-tips']).tips is False


def test_tips_command(ui, tmp_path, monkeypatch):
    cfg = tmp_path/'config.toml'
    monkeypatch.setenv('RAMABANA_CONFIG', str(cfg))
    for line, want in (('/tips off', False), ('/tips on', True), ('/tips', False), ('/tips', True)):
        ui.buf.insert(line)
        assert ui.submit() is None and ui.tips is want, line
    ui.buf.insert('/tips sideways'); ui.submit()
    assert ui.tips is True and 'usage: /tips' in ui.transcript.block_text(list(ui.comp.blocks.values())[-1])
    assert not cfg.exists(), 'nothing is written without --save'
    ui.buf.insert('/tips off --save'); ui.submit()
    assert ui.tips is False and load_config()[0] == {'cli.tips': False}


TOKEN = re.compile(r'ctrl\+\w|alt\+[\w.]+|shift\+\w+|/\w+|!COMMAND|#note|@path|^(?:\?|enter)(?= )')


def test_every_tip_names_a_real_key_or_command():
    assert 10 <= len(cli.TIPS) <= 15 and len(set(cli.TIPS)) == len(cli.TIPS)
    for tip in cli.TIPS:
        assert len(tip) <= 62 and 'shift+enter' not in tip, tip
        named = TOKEN.findall(tip)
        assert named, f'{tip!r} names no key or command'
        for tok in named: assert {'?': ' ? ', 'enter': 'enter send'}.get(tok, tok) in cli.HELP, (tok, tip)


def test_the_tip_row_never_wraps(ui):
    rows_of = lambda rows: sum(len(ui.comp.console.render_lines(r, pad=False)) for r in rows)
    for n in range(1, len(cli.TIPS) + 1):
        rows = _working(ui, n).working()
        assert rows_of(rows) == rows_of(rows[:-1]) + 1, cli.TIPS[n - 1]