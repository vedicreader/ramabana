"""The emblem and the palettes: what the terminal says about itself without being asked.

Two faults these pin. The status mark used to be one braille cell, so nothing about the surface
minded whether a mark was one cell wide; the arrow is five, rotates, and is repainted ten times a
second, so a state whose mark measured differently from another would shove the model name and the
running cost sideways on every frame. And `set_theme` used to know two names, so every place that
described the choice could spell the whole list out; there are thirteen now, and a palette missing
one semantic key does not fail where it is defined, it fails hours later inside an f-string in
whichever widget happened to read that key first.

Nothing here loads a model, and nothing here touches a real terminal.
"""
import pytest
from rich.cells import cell_len

from ramabana.cli import (ARROW, BANNER_GAP, BANNER_MIN, BOW, FLIGHT, FLIGHT_WIDTH, GUTTERS,
                          MARK_WIDTH, SLACK, THEMES, WORDMARK, ACTIVE_THEME, arrow_mark, banner,
                          code_theme, flight_line, set_theme)

#: Every key `_theme_parts`, the gutters, the emblem and the widgets read off a palette.
KEYS = frozenset({'bg0', 'bg1', 'bg2', 'fg0', 'fg1', 'gray',
                  'red', 'green', 'yellow', 'blue', 'aqua', 'orange'})


@pytest.fixture(autouse=True)
def back_to_dark():
    "Leave the module-level palette as it was found, whatever a test in here selected."
    was = ACTIVE_THEME
    yield
    set_theme(was)


def test_every_palette_carries_every_semantic_key():
    for name, palette in THEMES.items():
        assert set(palette) == KEYS, f'{name}: missing {KEYS - set(palette)}, extra {set(palette) - KEYS}'


def test_every_palette_is_hex_a_terminal_can_take():
    for name, palette in THEMES.items():
        for key, value in palette.items():
            assert isinstance(value, str) and value.startswith('#') and len(value) == 7, f'{name}.{key} = {value!r}'
            int(value[1:], 16)


def test_selecting_a_palette_restyles_the_gutters_and_the_markdown():
    "`set_theme` rebuilds `GUTTERS` in place, which is how `/theme` restyles what is already painted."
    set_theme('dark')
    from ramabana import cli
    dark = cli.GUTTERS['user'][0].copy()
    set_theme('dracula')
    assert cli.GRUVBOX is THEMES['dracula']
    assert cli.GUTTERS['user'][0].style != dark.style, 'the gutters kept the old palette'
    assert cli.ACTIVE_THEME == 'dracula'


def test_every_palette_is_reachable_by_name_and_auto_still_means_dark():
    for name in THEMES: assert set_theme(name) == name
    assert set_theme('auto') == 'dark'
    assert set_theme('DRACULA') == 'dracula', 'a name typed in capitals was refused'
    assert set_theme('') == 'dark'


def test_an_unknown_palette_is_one_sentence_with_the_near_miss_in_it():
    "`main` prints this to stderr and returns 2, so it has to read as a sentence, not a table."
    with pytest.raises(ValueError) as e:
        set_theme('draculaa')
    msg = str(e.value)
    assert 'dracula' in msg and 'did you mean' in msg, msg
    assert '\n' not in msg and 'gruvbox' not in msg, f'the whole list is still in it: {msg}'

    with pytest.raises(ValueError) as e:
        set_theme('wat')
    assert '/theme' in str(e.value) and 'nord' not in str(e.value), str(e.value)


def test_the_banner_has_a_gutter_that_does_not_bullet_it():
    "A `note` gutter would put a `· ` beside the top limb of the bow."
    assert GUTTERS['banner'][0].plain.strip() == ''


def test_every_state_of_the_status_mark_measures_the_same():
    """The status bar repaints ten times a second. A mark that grew by a cell as a turn started, or
    mid-rotation, would shove the model name and the cost sideways on every frame.
    """
    widths = {cell_len(arrow_mark(state, frame).plain)
              for state in ('working', 'ready', 'idle', 'anything else')
              for frame in range(MARK_WIDTH * 3)}
    assert widths == {MARK_WIDTH}, widths
    assert len(SLACK) == MARK_WIDTH


def test_the_working_mark_always_shows_exactly_one_arrowhead():
    """The first try rotated a ring, which split the arrow at the wrap: a head at one end of the
    strip and a bare tail at the other, sitting beside the word `working` like debris.
    """
    frames = [arrow_mark('working', f).plain for f in range(MARK_WIDTH)]
    assert len(set(frames)) == MARK_WIDTH, f'the cycle repeats inside one turn of it: {frames}'
    for f in frames: assert f.count('▸') == 1, f'{f!r} has {f.count("▸")} heads'
    assert arrow_mark('working', MARK_WIDTH).plain == frames[0], 'the cycle does not close'
    heads = [f.index('▸') for f in frames]
    assert heads == sorted(heads), f'the head went backwards: {heads}'
    assert arrow_mark('ready', 3).plain == arrow_mark('ready', 9).plain, 'a still mark moved'


def test_the_mark_and_the_flight_line_are_drawn_from_the_same_arrow():
    "Two arrows that disagreed about their own glyphs would read as two different things."
    assert ARROW[-1] == '▸' and ''.join(g for g, _ in FLIGHT).endswith(ARROW[1:])


def test_the_three_states_are_told_apart_by_shape_and_not_only_by_colour():
    "A terminal with no colour, or a reader who cannot see it, still has to be able to read the bar."
    plains = {s: arrow_mark(s, 0).plain for s in ('working', 'ready', 'idle')}
    assert '▸' in plains['ready'] and '▸' not in plains['idle'], plains
    assert plains['ready'] != plains['idle']


def test_the_flight_track_is_constant_width_and_the_arrow_crosses_it():
    for width in (len(FLIGHT), 12, FLIGHT_WIDTH, 40):
        seen = {cell_len(flight_line(f, width).plain) for f in range(width * 2 + 8)}
        assert seen == {width}, (width, seen)
    heads = [flight_line(f, 20).plain.index('▸') for f in range(20) if '▸' in flight_line(f, 20).plain]
    assert heads == sorted(heads) and len(heads) > 10, heads


def test_the_flight_track_never_goes_narrower_than_the_arrow_is_long():
    "A track of two cells used to slice the arrow into a puzzle. It clamps instead."
    assert cell_len(flight_line(0, 1).plain) == len(FLIGHT)


def test_the_emblem_is_drawn_in_alphabets_that_do_not_overlap():
    """`_glyphs` colours the arrow apart from the bow by glyph alone, and the wordmark is appended
    already styled. Sharing a glyph between the three would colour the wrong stroke.
    """
    from ramabana.cli import _ARROW_GLYPHS, _BOW_GLYPHS
    assert not set(_ARROW_GLYPHS) & set(_BOW_GLYPHS)
    word = set(''.join(WORDMARK)) - {' '}
    assert not word & (set(_ARROW_GLYPHS) | set(_BOW_GLYPHS))
    assert set(''.join(BOW)) - {' '} <= set(_ARROW_GLYPHS) | set(_BOW_GLYPHS)


def test_the_bow_has_a_middle_row_and_room_beside_it_for_the_name():
    "The arrow flies down the bow's middle row, and the wordmark straddles it with the note under."
    assert len(BOW) % 2 == 1, 'an even-height bow has no row for the arrow to fly down'
    assert len(BOW) >= len(WORDMARK) + 2, 'no room beside the bow for the wordmark and the note'
    assert '▸' in BOW[len(BOW) // 2], 'the arrow is not on the middle row'
    assert len({len(w) for w in WORDMARK}) == 1, 'the wordmark rows are ragged'
    assert BANNER_MIN == max(map(len, BOW)) + BANNER_GAP + len(WORDMARK[0])


#: Which cell edges each glyph of the bow puts a stroke through.
JOINS = {'─': 'lr', '━': 'lr', '│': 'ud', '┿': 'lrud', '╭': 'rd', '╮': 'ld', '╰': 'ru',
         '╯': 'lu', '≺': 'r', '▸': 'l', ' ': ''}


def test_every_stroke_of_the_bow_joins_the_next():
    """The fault this pins: the first bow was drawn by eye, out of diagonals and rounded corners a
    *font* blurs into looking joined. A terminal that draws its own box characters -- Ghostty, and
    so conterm -- meets them exactly across a cell edge, and rendered honestly that bow was a bag of
    loose ends. Every stroke reaching a cell edge must be met by one reaching back.
    """
    grid = [row.ljust(max(map(len, BOW))) for row in BOW]
    assert set(''.join(grid)) <= set(JOINS), f'undescribed glyphs: {set("".join(grid)) - set(JOINS)}'
    at = lambda r, c: JOINS[grid[r][c]] if 0 <= r < len(grid) and 0 <= c < len(grid[0]) else ''
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            assert ('r' in at(r, c)) == ('l' in at(r, c + 1)), f'row {r}, between cols {c} and {c+1}'
            assert ('d' in at(r, c)) == ('u' in at(r + 1, c)), f'col {c}, between rows {r} and {r+1}'


def test_the_bow_is_shaped_like_a_bow_and_not_like_a_box():
    """A terminal cell is about twice as tall as it is wide, so the bow's proportions on screen are
    not its proportions in the source. A real bow is a good deal taller than it is deep.
    """
    stave = min(BOW[len(BOW) // 2].index('┿'), BOW[0].index('╭'))
    belly = max(row.rindex('╮') if '╮' in row else 0 for row in BOW)
    on_screen = (belly - stave) / (len(BOW) * 2)     # cells are ~1:2, so rows count double
    assert 0.5 <= on_screen <= 0.85, f'depth/height reads as {on_screen:.2f} on screen'


def test_the_banner_fits_the_width_it_was_given():
    """It goes into a block with a two-cell gutter, so a row wider than the terminal wraps and the
    bow stops being a bow. Each tier has to fit inside what it was told it had.
    """
    for width, rows in ((100, len(BOW)), (BANNER_MIN, len(BOW)),
                        (BANNER_MIN - 1, len(WORDMARK) + 1), (len(WORDMARK[0]) + 1, 1)):
        out = banner('gemma-e2b', width).plain.split('\n')
        assert len(out) == rows, (width, len(out), rows)
        assert max(cell_len(r) for r in out) <= width, (width, out)


def test_the_note_cannot_widen_the_bow_or_add_a_row_to_it():
    """`agent.note` is whatever the session had to say -- `agent_err` output included -- so it
    arrives long, and can arrive with a newline in it. Either one used to break the art: the
    newline added rows, and a long note pushed its own row past the width the caller allowed.
    """
    long = 'skills unavailable (Traceback most recent call last\nRuntimeError: ' + 'x' * 300 + ')'
    for width in (26, 40, BANNER_MIN - 1, BANNER_MIN, 60, 120):
        out = banner(long, width).plain.split('\n')
        assert max(cell_len(r) for r in out) <= width, (width, [cell_len(r) for r in out])
        assert len(out) <= len(BOW) + 1, (width, len(out))
        assert '\n' not in banner(long, width).plain.replace('\n', '', len(out) - 1)
    assert '…' in banner(long, 120).plain, 'a clipped note does not say it was clipped'
    assert 'RAMABANA' not in banner('', 120).plain, 'the wordmark is drawn, not spelled'
    assert banner('', 20).plain == 'RAMABANA', 'the narrowest tier lost the name'
    assert banner(long, 0).plain == 'RAMABANA', 'a nonsense width still has to return something'
    assert len(banner(long).plain.split('\n')) == len(BOW), 'no width means no limit, not no bow'


def test_the_banner_takes_the_palette_it_is_handed_over_the_active_one():
    "A theme demo paints one banner per palette without selecting each one first."
    set_theme('dark')
    painted = ' '.join(str(s.style) for s in banner('', 100, THEMES['nord']).spans)
    assert THEMES['nord']['orange'] in painted, painted
    assert THEMES['dark']['orange'] not in painted, 'the active palette leaked in'


def test_every_palette_names_a_code_theme_pygments_really_ships():
    from pygments.styles import get_all_styles
    have = set(get_all_styles())
    for name in THEMES:
        set_theme(name)
        assert code_theme() in have, f'{name} -> {code_theme()!r} is not a pygments style'
    assert code_theme('nothing like a theme') in have


def test_the_status_bar_shows_the_arrow_and_never_runs_it_into_the_state():
    """The mark used to be one braille cell followed by a hard-coded space. The ring rotates, so a
    frame can end on `━`, and `━working` was the result until the space became the bar's own.
    """
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    from ramabana.testing import fake_agent

    tty = EmuTty(100, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    try:
        agent, _ = fake_agent()
        ui = Ui(comp, agent)
        # A `fake_agent` has started nothing, so its two reachable states are working and idle.
        for frame in range(MARK_WIDTH * 2):
            ui.frame = frame
            for turn, state in (( 'a turn', 'working'), (None, 'idle')):
                ui.turn = turn
                bar = ui.status().plain
                at = bar.index(state)
                assert bar[at - 1] == ' ', f'the ring ran into the state: {bar!r}'
                assert ('▸' in bar) is (state == 'working'), (state, frame, bar)
    finally:
        tty.close()


def test_a_running_turn_puts_the_arrow_in_flight_above_the_prompt():
    "The `working` tail is the one place a reader watches while a turn runs, so the art belongs there."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    from ramabana.testing import fake_agent

    tty = EmuTty(100, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    try:
        agent, _ = fake_agent()
        ui = Ui(comp, agent)
        assert ui.working() == [], 'the flight line showed with no turn running'
        ui.turn = 'a turn'
        rows = [r.plain for r in ui.working()]
        assert '▸' in rows[-1], rows
        moved = {tuple(r.plain for r in (setattr(ui, 'frame', f), ui.working())[1]) for f in range(8)}
        assert len(moved) > 1, 'the arrow never moved across eight frames'
    finally:
        tty.close()


def test_a_narrow_terminal_still_gets_a_totals_row_it_can_read():
    "The flight track shares its row with the totals, so it has to give way rather than push them off."
    from ramabana.cli import flight_line
    assert cell_len(flight_line(0, max(len(FLIGHT), 30 - 40)).plain) == len(FLIGHT)


def test_the_python_prompt_highlights_in_the_palette_the_session_is_wearing():
    """`hl` held `gruvbox-dark` whatever the palette, so a pale theme got dark code under it. It
    asks `code_theme` now. The import is inside the function, because `cli` reaches `hl` the same
    way and a module-level one either way round is a cycle.
    """
    from ramabana.pyrepl import hl
    styles = {}
    for name in ('dark', 'latte', 'gruvbox', 'solarized-light'):
        set_theme(name)
        styles[name] = [str(s.style) for s in hl('def f(x): return x + 1').spans]
        assert styles[name], f'{name}: nothing was highlighted at all'
    assert styles['latte'] != styles['dark'], 'a pale palette got the dark code theme'
    assert styles['gruvbox'] != styles['dark']
    assert hl('').plain == '' and hl('!!! not python').plain == '!!! not python'
