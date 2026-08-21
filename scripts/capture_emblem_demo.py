#!/usr/bin/env python
"""Drive the CLI over a headless Ghostty and record the emblem and the palettes as MP4 + GIF.

Two clips, written to the output folder (`media/` by default):

  ramabana-emblem  the banner, then a turn: the arrow loosed in the status bar and flying
                   beside the step count, then nocked and green again when the turn ends.
  ramabana-themes  the same screen carried through every palette in `THEMES`, as `/theme next`
                   does it, with the terminal's own background moved along with it.

No model is loaded and no network is touched: `fake_agent` answers, and the turn is driven through
the same `stream`/`activity` calls a real one goes through, so what is recorded is the real surface.

Wants ffmpeg on the path, and Pillow and fontTools importable -- neither is a dependency of the
package, because nothing but this script needs them. `preflight` names whatever is missing before
it draws a frame.
"""
from __future__ import annotations

import asyncio, shutil, subprocess, sys
from importlib.util import find_spec
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana.cli import THEMES, Ui, banner, set_theme
from ramabana.testing import fake_agent

COLS, ROWS = 100, 26
#: DejaVu Sans Mono advances 1233/2048 em, so 15px lands within a hair of a 9px cell -- which is
#: what the double-ruled wordmark needs, since that comes from the font rather than from `_strokes`.
CELL_W, CELL_H, FONT_PX = 9, 19, 15
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
EMOJI = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'
FPS = 10
#: The 16 ANSI slots, for anything that asks for a palette colour rather than an rgb one.
ANSI = ((40, 42, 46), (204, 102, 102), (152, 151, 26), (215, 153, 33), (69, 133, 136),
        (177, 98, 134), (104, 157, 106), (168, 153, 132), (102, 92, 84), (251, 73, 52),
        (184, 187, 38), (250, 189, 47), (131, 165, 152), (211, 134, 155), (142, 192, 124),
        (235, 219, 178))


def preflight():
    """Say what is missing before a single frame is drawn, rather than part-way through.

    Every one of these failed late and badly before: no ffmpeg meant rendering a whole clip and
    then dying on the encode, twice, because `main` runs both; a mono font PIL cannot open threw
    `OSError: cannot open resource` *after* `Clip.__init__` had already cleared the frames folder;
    and a missing emoji font failed silently, leaving tofu where the tool icons should be.
    """
    missing = []
    if shutil.which('ffmpeg') is None: missing.append('ffmpeg (apt install ffmpeg)')
    # fontTools is reached lazily, by `_mono_cmap`, so it is the one import that can fail late.
    # Pillow is imported at the top of this file and says so itself.
    if find_spec('fontTools') is None: missing.append('fontTools (uv add --group dev fonttools)')
    if not Path(FONT).exists():
        missing.append(f'a mono font at {FONT} (apt install fonts-dejavu-core)')
    if missing:
        raise SystemExit('cannot record the demo without:\n  ' + '\n  '.join(missing))
    if not Path(EMOJI).exists():
        print(f'  note: no emoji font at {EMOJI}; tool icons will render as tofu', file=sys.stderr)


def rgb(hex_or_none, fallback):
    "A `#rrggbb` string as a triple."
    if not hex_or_none: return fallback
    h = hex_or_none.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _colour(entry, fallback):
    "One of the emulator's `('rgb', ...)` / `('palette', n)` cell colours as a triple."
    if entry is None: return fallback
    kind, val = entry
    if kind == 'rgb': return tuple(val)
    return ANSI[int(val) % 16] if kind == 'palette' else fallback


#: The glyphs the emblem is built from, drawn as strokes in the cell rather than set from the font.
#: A terminal that draws its own box characters -- Ghostty, and so conterm -- makes them meet across
#: the cell edge exactly; a font blitted into a grid leaves a seam at every join, and a bow made of
#: seams is not a bow. Everything outside this table still comes from the font.
LIGHT, HEAVY, DOUBLE = 0.085, 0.17, 0.075


def _strokes(ch):
    "`(kind, *args)` strokes in cell coordinates (0..1 both ways), or None to use the font."
    h, v = ('h', 0.5, 0.0, 1.0), ('v', 0.5, 0.0, 1.0)
    return {
        '─': [h + (LIGHT,)],                    '━': [h + (HEAVY,)],
        '│': [v + (LIGHT,)],                    '┃': [v + (HEAVY,)],
        '┿': [v + (LIGHT,), h + (HEAVY,)],      '┼': [v + (LIGHT,), h + (LIGHT,)],
        '┤': [v + (LIGHT,), ('h', 0.5, 0.0, 0.5, LIGHT)],
        '╴': [('h', 0.5, 0.0, 0.5, LIGHT)],     '╶': [('h', 0.5, 0.5, 1.0, LIGHT)],
        '╭': [('arc', 1.0, 1.0, LIGHT)],        '╮': [('arc', 0.0, 1.0, LIGHT)],
        '╰': [('arc', 1.0, 0.0, LIGHT)],        '╯': [('arc', 0.0, 0.0, LIGHT)],
        '╱': [('d', 0.0, 1.0, 1.0, 0.0, LIGHT)], '╲': [('d', 0.0, 0.0, 1.0, 1.0, LIGHT)],
        '┄': [('dash', 3, LIGHT)],              '┈': [('dash', 4, LIGHT)],
        '≺': [('d', 1.0, 0.12, 0.16, 0.5, LIGHT), ('d', 0.16, 0.5, 1.0, 0.88, LIGHT)],
        '▸': [('tri', 0.22, 0.1, 0.86, 0.5, 0.22, 0.9)],
        '▌': [('rect', 0.0, 0.0, 0.5, 1.0)],
        '·': [('dot', 0.5, 0.5, 0.09)],
        '┆': [('vdash', 2, LIGHT)],
    }.get(ch)


def _paint_cell(draw, x0, y0, ch, colour):
    "One drawn glyph, in the cell whose top-left corner is (`x0`, `y0`). True when it was drawn."
    st = _strokes(ch)
    if st is None: return False
    W, H = CELL_W, CELL_H
    px = lambda fx, fy: (x0 + fx * W, y0 + fy * H)
    for stroke in st:
        kind = stroke[0]
        if kind == 'h':
            y, a, b, w = stroke[1:]
            t = max(1, round(w * H))
            draw.rectangle([x0 + a * W, y0 + y * H - t / 2, x0 + b * W - 1, y0 + y * H + t / 2], fill=colour)
        elif kind == 'v':
            x, a, b, w = stroke[1:]
            t = max(1, round(w * W * 2))
            draw.rectangle([x0 + x * W - t / 2, y0 + a * H, x0 + x * W + t / 2, y0 + b * H - 1], fill=colour)
        elif kind == 'd':
            ax, ay, bx, by, w = stroke[1:]
            draw.line([px(ax, ay), px(bx, by)], fill=colour, width=max(1, round(w * W * 1.6)))
        elif kind == 'arc':
            # A quarter turn from the cell centre out to the (`tx`,`ty`) edge, so `╭╮╰╯` round off.
            tx, ty = stroke[1], stroke[2]
            w = max(1, round(stroke[3] * W * 2))
            pts = []
            for i in range(13):
                t = i / 12
                # quadratic through the centre-adjacent corner: a real rounded corner, not a chamfer
                cx, cy = 0.5 + (tx - 0.5) * 0.0, 0.5 + (ty - 0.5) * 0.0
                sx, sy = (tx, 0.5) if tx in (0.0, 1.0) else (0.5, ty)
                ex, ey = (0.5, ty) if tx in (0.0, 1.0) else (tx, 0.5)
                u = 1 - t
                pts.append(px(u * u * sx + 2 * u * t * cx + t * t * ex,
                              u * u * sy + 2 * u * t * cy + t * t * ey))
            draw.line(pts, fill=colour, width=w, joint='curve')
        elif kind == 'dash':
            n, w = stroke[1], stroke[2]
            t = max(1, round(w * H))
            for i in range(n):
                a, b = i / n + 0.06, (i + 1) / n - 0.06
                draw.rectangle([x0 + a * W, y0 + 0.5 * H - t / 2, x0 + b * W, y0 + 0.5 * H + t / 2], fill=colour)
        elif kind == 'vdash':
            n, w = stroke[1], stroke[2]
            t = max(1, round(w * W * 2))
            for i in range(n):
                a, b = i / n + 0.08, (i + 1) / n - 0.08
                draw.rectangle([x0 + 0.5 * W - t / 2, y0 + a * H, x0 + 0.5 * W + t / 2, y0 + b * H], fill=colour)
        elif kind == 'tri':
            draw.polygon([px(*stroke[1:3]), px(*stroke[3:5]), px(*stroke[5:7])], fill=colour)
        elif kind == 'rect':
            ax, ay, bx, by = stroke[1:]
            draw.rectangle([px(ax, ay), (x0 + bx * W - 1, y0 + by * H - 1)], fill=colour)
        elif kind == 'dot':
            cx, cy, r = stroke[1:]
            draw.ellipse([px(cx - r, cy - r * W / H * 2), px(cx + r, cy + r * W / H * 2)], fill=colour)
    return True


def render(term, path, bg, fg, label=''):
    "One screen of the emulator as a PNG, on `bg`, with an optional caption under it."
    pad, cap = 14, 28 if label else 0
    img = Image.new('RGB', (COLS * CELL_W + pad * 2, ROWS * CELL_H + pad * 2 + cap), bg)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, FONT_PX)
    try: emoji = ImageFont.truetype(EMOJI, 109)   # NotoColorEmoji is a bitmap font: 109 or nothing
    except Exception: emoji = None
    for y, line in enumerate(term.text().splitlines()[:ROWS]):
        for x, ch in enumerate(line[:COLS]):
            if ch == ' ': continue
            st = term.style(x, y)
            cell_fg, cell_bg = _colour(st.get('fg'), fg), _colour(st.get('bg'), bg)
            if st.get('inverse'): cell_fg, cell_bg = cell_bg, cell_fg
            if st.get('bold'): cell_fg = tuple(min(255, c + 22) for c in cell_fg)
            x0, y0 = pad + x * CELL_W, pad + y * CELL_H
            if cell_bg != bg: draw.rectangle([x0, y0, x0 + CELL_W - 1, y0 + CELL_H - 1], fill=cell_bg)
            if _paint_cell(draw, x0, y0, ch, cell_fg): continue
            if ch not in _mono_cmap() and emoji is not None:
                tile = _emoji_tile(ch, emoji)
                if tile is not None:
                    img.paste(tile, (x0, y0 + 2), tile)
                    continue
            draw.text((x0, y0 + 1), ch, fill=cell_fg, font=font)
    if label:
        draw.text((pad, pad + ROWS * CELL_H + 5), label,
                  fill=tuple(min(255, c + 95) if bg[0] < 128 else max(0, c - 95) for c in bg),
                  font=ImageFont.truetype(FONT, 14))
    img.save(path)


def _mono_cmap():
    "Every character the mono font can actually set. Anything else is tofu unless emoji covers it."
    if _mono_cmap.chars is None:
        from fontTools.ttLib import TTFont
        f = TTFont(FONT, fontNumber=0)
        _mono_cmap.chars = {chr(cp) for t in f['cmap'].tables for cp in t.cmap}
    return _mono_cmap.chars
_mono_cmap.chars = None


def _emoji_tile(ch, font):
    """One colour emoji scaled into a cell, cached, or None when the emoji font has not got it.

    Routing on codepoint alone swallowed the whole wordmark once: `═` is above the emoji ranges,
    NotoColorEmoji has nothing for it, and the empty tile was pasted over it in silence.
    """
    if ch not in _emoji_tile.cache:
        tile = Image.new('RGBA', (150, 150), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((5, 5), ch, font=font, embedded_color=True)
        box = tile.getbbox()
        _emoji_tile.cache[ch] = (None if box is None else
                                 tile.crop(box).resize((CELL_W, CELL_H - 4), Image.LANCZOS))
    return _emoji_tile.cache[ch]
_emoji_tile.cache = {}


class Clip:
    "A frame sink that repeats each screen for as long as it should stay up, then encodes it."

    def __init__(self, out, name):
        self.dir, self.name, self.n = out/'frames'/name, name, 0
        if self.dir.exists(): shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.out = out

    def add(self, term, bg, fg, hold=1, label=''):
        "One screen, held for `hold` frames."
        first = self.dir/f'{self.n:05d}.png'
        render(term, first, bg, fg, label)
        self.n += 1
        for _ in range(hold - 1):
            shutil.copy(first, self.dir/f'{self.n:05d}.png')
            self.n += 1

    def encode(self, width=1000, gif_width=820):
        "The frames as an MP4 and a looping GIF, the GIF narrower so a README can carry it."
        mp4, gif = self.out/f'{self.name}.mp4', self.out/f'{self.name}.gif'
        subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS),
                               '-i', str(self.dir/'%05d.png'), '-c:v', 'libx264',
                               '-pix_fmt', 'yuv420p', '-crf', '20',
                               '-vf', f'scale={width}:-2:flags=lanczos', str(mp4)])
        palette = self.dir/'palette.png'
        common = f'fps={FPS},scale={gif_width}:-1:flags=lanczos'
        subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(mp4),
                               '-vf', f'{common},palettegen=max_colors=192', str(palette)])
        subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(mp4), '-i', str(palette),
                               '-lavfi', f'{common}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3',
                               '-loop', '0', str(gif)])
        print(f'  {self.name}: {self.n} frames · mp4 {mp4.stat().st_size//1024}k · gif {gif.stat().st_size//1024}k')
        return mp4, gif


async def surface(theme='dark'):
    "A whole CLI over a headless Ghostty, with a fake agent that reports itself loaded and ready."
    set_theme(theme)
    tty = EmuTty(COLS, ROWS, bg=rgb(THEMES[theme]['bg0'], (0, 0, 0)))
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    await comp.start()
    agent, backend = fake_agent()
    real = agent.status
    def status():
        s = real()
        return s | dict(model='gemma-3n-e2b', ready=True, ntools=26, nskills=13, pct_full=0.07)
    agent.status = status
    ui = Ui(comp, agent)
    return tty, comp, agent, ui


def bgfg(theme):
    p = THEMES[theme]
    return rgb(p['bg0'], (0, 0, 0)), rgb(p['fg1'], (255, 255, 255))


#: The turn the emblem clip records: what the model says, the call it makes, and what comes back.
TURN = [('Reading the surface first.\n', 'view_file', {'path': 'nbs/05_cli.ipynb'}, 'ok, 1771 lines'),
        ('The bow is drawn once, at startup.\n', 'search_code', {'query': 'banner'}, 'cli.py:246'),
        ('And the arrow flies while a turn runs.\n', 'run_tests', {'path': 'tests/test_emblem.py'}, '20 passed')]

ANSWER = ('## The emblem\n\n'
          'One drawing, two states. `banner` opens with the bow drawn and the arrow on the '
          'string; `arrow_mark` keeps that arrow in the status bar, and `flight_line` looses it '
          'while a turn runs.\n')


async def emblem_clip(out):
    "The banner, a turn running with the arrow in flight, and the mark nocked and green after it."
    tty, comp, agent, ui = await surface('dark')
    bg, fg = bgfg('dark')
    clip = Clip(out, 'ramabana-emblem')
    try:
        ui.say(banner("gemma-3n-e2b · rama's arrow, on the string", COLS - 4), 'banner', fold=None)
        ui.hint = '~/ramabana · /python · /help'
        ui.paint()
        clip.add(tty.term, bg, fg, hold=18)            # the banner, held long enough to read

        line = 'draw me the bow, and keep the arrow flying while you work'
        for i, ch in enumerate(line):
            comp.on_bytes(ch.encode())
            if i % 3 == 0: ui.paint(); clip.add(tty.term, bg, fg)
        ui.paint(); clip.add(tty.term, bg, fg, hold=8)
        ui.buf.clear()

        ui.say(line, 'user', fold=None)
        ui._turn_at, ui.turn = __import__('time').monotonic(), 'a turn'
        seg, acts = None, agent.activity
        for prose, tool, args, result in TURN:
            seg = ui.stream(seg, prose)
            act = acts.start(tool, args)
            for _ in range(9):                          # the arrow crosses while the call is out
                ui.frame += 1; ui.paint(); clip.add(tty.term, bg, fg)
            acts.finish(act, result)
            ui.frame += 1; ui.paint(); clip.add(tty.term, bg, fg, hold=3)

        ui.turn = None
        ui.flush_stream()
        ui.say(ui.reply(ANSWER), 'reply', fold=None, source=ANSWER)
        for f in range(10):                             # nocked and green again
            ui.frame += 1; ui.paint(); clip.add(tty.term, bg, fg, hold=2)
        ui.paint(); clip.add(tty.term, bg, fg, hold=20)
    finally:
        for t in list(comp._tasks): t.cancel()
        await asyncio.sleep(0.05)
        try: comp.stop()
        except Exception: pass
        tty.close()
    return clip.encode()


async def themes_clip(out):
    "One screen, carried through every palette the way `/theme next` carries it."
    clip = Clip(out, 'ramabana-themes')
    names = list(THEMES)
    for name in names:
        tty, comp, agent, ui = await surface(name)
        bg, fg = bgfg(name)
        try:
            ui.apply_theme(name)
            ui.say(banner(f'gemma-3n-e2b · {name}', COLS - 4), 'banner', fold=None)
            ui.hint = '~/ramabana · /theme next · /help'
            ui.say('which palettes are there?', 'user', fold=None)
            ui.say(ui.reply(f'## /theme {name}\n\nThirteen palettes, `{name}` among them: the '
                            'schemes a **conterm** or Ghostty window already ships, so the surface '
                            'and the window agree.\n\n```python\nset_theme({!r})\n```\n'.format(name)),
                   'reply', fold=None)
            ui._turn_at, ui.turn = __import__('time').monotonic(), 'a turn'
            act = agent.activity.start('search_code', {'query': 'set_theme'})
            for f in range(7):
                ui.frame += 1; ui.paint(); clip.add(tty.term, bg, fg, label=f'/theme {name}')
            agent.activity.finish(act, 'cli.py:118')
            ui.turn = None
            ui.paint(); clip.add(tty.term, bg, fg, hold=9, label=f'/theme {name}')
        finally:
            for t in list(comp._tasks): t.cancel()
            await asyncio.sleep(0.05)
            try: comp.stop()
            except Exception: pass
            tty.close()
    set_theme('dark')
    return clip.encode()


async def main(out):
    preflight()
    out.mkdir(parents=True, exist_ok=True)
    print('emblem:');  await emblem_clip(out)
    print('themes:');  await themes_clip(out)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else 'media')))
