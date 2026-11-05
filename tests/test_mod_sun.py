from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.style import Style
from shalya.skills import Registry, check


MOD = Path(__file__).parents[1] / 'examples/mods/sun'


MODULE = run_path(str(MOD / 'mod.py'))


def fresh():
    reg = Registry()
    MODULE['setup'](reg)
    return reg, reg.bands[0], reg.commands['sun'][0]


@pytest.fixture
def sun(): return fresh()


def view(t=100, busy=True, width=60, rows=11, busy_since=None, theme='dark', colors='truecolor'):
    return SimpleNamespace(agent=None, busy=busy, t=t, width=width, rows=rows, busy_since=busy_since, theme=theme, colors=colors)


def text(frame):
    return [''.join(part for part, style in row) for row in frame]


def pixels(frame):
    "Every painted half-cell of the art rows as `(x, y, (r, g, b))`."
    out = []
    for y, row in enumerate(frame[:-1]):
        x = 0
        for part, style in row:
            parsed = Style.parse(style)
            if part in ('▀', '▄'):
                out.append((x, 2 * y + (part == '▄'), parsed.color.get_truecolor()))
                if parsed.bgcolor: out.append((x, 2 * y + 1, parsed.bgcolor.get_truecolor()))
            x += cell_len(part)
    return out


def luminance(c): return .2126 * c.red + .7152 * c.green + .0722 * c.blue


def extent(frame):
    "The columns spanned by the art rows, and the number of art rows with anything in them."
    art = text(frame)[:-1]
    cols = [x for row in art for x, c in enumerate(row) if not c.isspace()]
    return max(cols) - min(cols) + 1, sum(bool(row.strip()) for row in art)


def test_registration():
    result = check(MOD)
    assert result['mods'][0]['on'], result['mods'][0]['note']
    assert result['bands'] == [{'rows': 11}]
    assert result['commands'] == ['sun']
    assert result['timers'] == []


def test_frame_bounds_and_styles(sun):
    reg, band, command = sun
    assert band(view(busy=False)) is None
    for colors in ('truecolor', 'standard', 'none'):
        for width in (0, 1, 9, 19, 20, 24, 28, 60):
            for rows in range(12):
                frame = band(view(width=width, rows=rows, colors=colors))
                assert len(frame) <= rows
                assert all(cell_len(row) <= width for row in text(frame))
                for row in frame:
                    for part, style in row:
                        Style.parse(style)
                        if not part.strip():
                            assert 'on ' not in style
                if width < 20 and rows and width:
                    assert len(frame) == 1
                    assert text(frame)[0].strip() == 'breathe in'[:width]


def test_breath_and_restart(sun):
    reg, band, command = sun
    trough = band(view())
    peak = band(view(104))
    assert extent(peak)[0] - extent(trough)[0] >= 10
    assert extent(peak)[1] == 10 and extent(peak)[0] >= 18
    assert extent(trough)[0] <= 10
    assert peak == band(view(104))
    assert text(trough)[-1].strip() == 'breathe in'
    assert text(peak)[-1].strip() == 'breathe out'
    label = text(peak)[-1]
    assert abs((len(label.rstrip()) + len(label) - len(label.lstrip())) / 2 - 30) <= 1
    assert band(view(110)) == trough
    assert band(view(111, busy=False)) is None
    assert band(view(150)) == trough
    reg.fire('after_turn', None, '')
    assert band(view(203)) == trough
    reg.fire('stop', None, '')
    assert band(view(257)) == trough
    reg.fire('session_end', None)
    assert band(view(311)) == trough


def test_rays_are_proportional_in_pixels(sun):
    reg, band, command = sun
    painted = {(x, y) for x, y, c in pixels(band(view(104)))}
    centre = (60 - 25) // 2 + 12
    across = [x for x, y in painted if y in (9, 10)]
    down = [y for x, y in painted if x == centre]
    assert max(across) - min(across) + 1 <= 1.5 * (max(down) - min(down) + 1)


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_core_is_the_brightest(sun, theme):
    reg, band, command = sun
    band(view())
    for t in (100, 101, 102, 104, 107):
        frame = band(view(t, theme=theme))
        painted = pixels(frame)
        brightest = max(luminance(c) for x, y, c in painted)
        centre = (60 - 25) // 2 + 12
        core = [luminance(c) for x, y, c in painted if x == centre and y in (9, 10)]
        assert core and max(core) == brightest, (theme, t)
    assert band(view(104, theme='light')) != band(view(104, theme='dark'))


def test_busy_since_sets_the_phase():
    reg, band, command = fresh()
    assert text(band(view(104, busy_since=100)))[-1].strip() == 'breathe out'
    assert band(view(104, busy_since=100)) == MODULE['frame'](4, 60)
    reg, band, command = fresh()
    assert band(view(100, busy_since=100)) == band(view(110, busy_since=100))
    reg, band, command = fresh()
    assert text(band(view(104)))[-1].strip() == 'breathe in'
    reg, band, command = fresh()
    command(None, 'pace 5 7')
    assert text(band(view(300, busy_since=290)))[-1].strip() == 'breathe in'


def test_limited_colours(sun):
    reg, band, command = sun
    for t in (100, 104):
        standard = band(view(t, colors='standard'))
        assert all('#' not in style for row in standard for part, style in row)
        assert {s for row in standard for part, s in row if part.strip()} <= {'yellow', 'bright_yellow'} | {f'{a} on {b}' for a in ('yellow', 'bright_yellow') for b in ('yellow', 'bright_yellow')}
        plain = band(view(t, colors='none'))
        assert all(style == '' for row in plain for part, style in row)
        assert set(''.join(text(plain)[:-1])) <= set('*o. ')
    assert extent(band(view(104, colors='none')))[0] > extent(band(view(100, colors='none')))[0]


def test_commands_and_pace(sun):
    reg, band, command = sun
    assert 'on' in command(None, '')
    assert 'off' in command(None, 'off')
    assert band(view()) is None
    assert 'on' in command(None, 'on')
    band(view())
    assert '5' in command(None, 'pace 5 7')
    first = band(view(200))
    assert text(band(view(204.9)))[-1].strip() == 'breathe in'
    assert text(band(view(205)))[-1].strip() == 'breathe out'
    assert band(view(212)) == first
    before = command(None, '')
    for args in ('pace 1 7', 'pace 5 13', 'pace nan 7', 'pace inf 7', 'pace nope 7', 'pace 5', 'unknown'):
        assert 'Usage:' in command(None, args)
        assert command(None, '') == before
    assert 'inhale 2s, exhale 12s; period 14s' in command(None, 'pace 2 12')
