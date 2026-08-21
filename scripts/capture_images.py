#!/usr/bin/env python
"""Drive a drawing turn headlessly and capture what a kitty-graphics terminal would show.

pyghostty gives text and style, not pictures, so the graphics protocol is emulated here: the
byte stream is split at every APC, the emulator is fed the text between them, and the cursor is
read at each escape -- so a placement is recorded at exactly the cell the terminal would use.
The frames are then the text render with those images pasted over it.
"""
from __future__ import annotations

import asyncio, os, re, shutil, sys, tempfile
from pathlib import Path

os.environ.setdefault('TERM', 'xterm-256color')
os.environ['RAMABANA_KITTY'] = '1'
os.environ.setdefault('OPENAI_API_KEY', 'not-a-real-key')

from base64 import b64decode, b64encode
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana.agent import Agent
from ramabana.cli import Ui, run_turn, set_theme
from ramabana.testing import MemHost, ScriptedBackend, Step

COLS, ROWS = 100, 30
CELL_W, CELL_H = 9, 18
BG, FG = (10, 12, 16), (230, 237, 243)
PALETTE = {0: BG, 1: (255, 123, 114), 2: (63, 185, 80), 3: (210, 153, 34), 4: (88, 166, 255),
           5: (188, 140, 255), 6: (57, 197, 207), 7: (201, 209, 217), 8: (139, 148, 158),
           9: (255, 123, 114), 10: (86, 211, 100), 11: (233, 196, 106), 12: (121, 192, 255),
           13: (210, 168, 255), 14: (86, 216, 226), 15: (240, 246, 252)}

#: Every kitty escape is `ESC _ G <control> ; <payload> ESC \`, and neither part carries an ESC.
APC = re.compile(r'\x1b_G([^;\x1b]*)(?:;([^\x1b]*))?\x1b\\')


class KittyTty:
    """`EmuTty` plus the graphics protocol: transmits are collected and placements are remembered
    at the cursor they arrived on.

    A placement lives until it is deleted, which is what the protocol says: erasing the cells
    under one does not remove it. That is the unforgiving half of the two behaviours a real
    terminal may have, so a placement left behind shows up in these frames as a picture where
    none belongs -- which is most of what capturing them is for."""

    def __init__(self, cols, rows):
        self.emu = EmuTty(cols, rows, bg=BG)
        self.images, self.placed = {}, {}
        self.chunks, self.sending = [], None   # only the first chunk of a transmit names the image

    def __getattr__(self, k): return getattr(self.emu, k)

    def write(self, data):
        at = 0
        for m in APC.finditer(data):
            self.emu.write(data[at:m.start()])
            self._apc(dict(kv.split('=', 1) for kv in m.group(1).split(',') if '=' in kv),
                      m.group(2) or '')
            at = m.end()
        self.emu.write(data[at:])

    def _apc(self, ctl, payload):
        act = ctl.get('a', 't')
        if act in ('t', 'T') or 'm' in ctl:
            if 'i' in ctl: self.sending = ctl['i']
            self.chunks.append(payload)
            if ctl.get('m', '0') == '0':
                raw = b64decode(''.join(self.chunks))
                self.images[self.sending] = Image.open(BytesIO(raw)).convert('RGB')
                self.chunks = []
        i = ctl.get('i', self.sending)
        if act in ('T', 'p'):
            x, y = self.emu.term.cursor
            self.placed[(i, ctl.get('p', '1'))] = (y, x, int(ctl.get('c', 1)), int(ctl.get('r', 1)))
        if act == 'd': self.placed.pop((i, ctl.get('p', '1')), None)


def render(tty, path):
    "One frame: the emulator's cells, with every live placement pasted over them."
    img = Image.new('RGB', (COLS * CELL_W, ROWS * CELL_H), BG)
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 14)
    except OSError: font = ImageFont.load_default()
    for y, line in enumerate(tty.emu.term.text().splitlines()[:ROWS]):
        for x, ch in enumerate(line[:COLS]):
            if ch == ' ': continue
            st = tty.emu.term.style(x, y)
            fg, bg = _rgb(st.get('fg'), FG), _rgb(st.get('bg'), BG)
            if st.get('inverse'): fg, bg = bg, fg
            if bg != BG: draw.rectangle([x * CELL_W, y * CELL_H, (x + 1) * CELL_W - 1, (y + 1) * CELL_H - 1], fill=bg)
            draw.text((x * CELL_W, y * CELL_H), ch, fill=fg, font=font)
    for (i, _), (row, col, c, r) in sorted(tty.placed.items()):
        pic = tty.images.get(i)
        if pic is None: continue
        img.paste(pic.resize((c * CELL_W, r * CELL_H), Image.LANCZOS), (col * CELL_W, row * CELL_H))
    img.save(path)
    return path


def _rgb(c, fallback):
    if c is None: return fallback
    kind, val = c
    if kind == 'rgb': return tuple(val)
    return PALETTE.get(int(val) % 16, fallback) if kind == 'palette' else fallback


def a_picture(label, size=(768, 512)):
    "A PNG worth looking at in a screenshot, so a frame shows a picture rather than a grey square."
    w, h = size
    img = Image.new('RGB', size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (30 + 200 * x // w, 40 + 150 * y // h, 200 - 120 * x // w)
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 96)
    except OSError: font = ImageFont.load_default()
    d.ellipse([w // 6, h // 6, 5 * w // 6, 5 * h // 6], outline=(255, 250, 235), width=12)
    d.text((w // 2, h // 2), label, fill=(255, 250, 235), font=font, anchor='mm')
    out = BytesIO()
    img.save(out, format='PNG')
    return out.getvalue()


async def capture(out: Path):
    if out.exists():
        assert out.is_dir() and all(f.suffix == '.png' for f in out.iterdir()), f'{out} holds more than frames'
        shutil.rmtree(out)
    out.mkdir(parents=True)
    os.chdir(tempfile.mkdtemp())          # the tool saves beside the session: keep that out of the repo
    set_theme('github-dark')
    tty = KittyTty(COLS, ROWS)
    comp = Compositor(tty); comp._register_signals = lambda: None
    await comp.start()

    import ramabana.tools as tools
    pics, asked = [a_picture('1'), a_picture('2')], []
    def fake_post(prompt, size, n, timeout=120):
        asked.append(prompt)
        return [{'b64_json': b64encode(pics[min(len(asked) - 1, len(pics) - 1)]).decode()}]
    tools._post_image = fake_post

    agent = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), extensions=False, subagents=False)
    # the prose goes in its own step: a tool call closes the reply segment, so narration split
    # across one reads as a half sentence in a screenshot
    script = [Step(tool=('generate_image', {'prompt': 'a blue bottle'})),
              Step(tool=('generate_image', {'prompt': 'a red bottle'})),
              Step('Both are above, each drawn as it landed. Ask for a change to either.')]
    be = ScriptedBackend(steps=script, token_delay=0.06, tools=agent.tools)
    agent.routing.spec = lambda job='turn', fallback=True: be.spec
    agent._be = agent._be_or_none = lambda job='turn': be
    ui = Ui(comp, agent, loop=asyncio.get_running_loop())
    ui.note('drawing, streamed into the transcript')
    ui.paint()

    shots = []
    def snap(tag):
        shots.append(render(tty, out / f'{len(shots):02d}-{tag}.png'))
        print(f'  {shots[-1].name}: {len(tty.placed)} placement(s), {len(tty.images)} image(s)')

    snap('before')
    for ch in 'draw me two bottles': comp.on_bytes(ch.encode())
    ui.paint(); snap('typed')

    # snap the moment each picture lands, so a frame exists from inside the turn rather than after it
    drawn = ui.show_pic
    def shown(path):
        blk = drawn(path)
        ui.paint()
        snap(f'picture-{len(ui.pics)}-mid-turn')
        return blk
    ui.show_pic = shown
    await comp.spawn(run_turn(ui, 'draw me two bottles'))
    ui.paint(); snap('done')

    blk = ui.comp.blocks[next(iter(ui.pics))]
    ui.comp.toggle(blk); snap('folded')
    ui.comp.toggle(blk); snap('unfolded')

    from teleprint.widgets import CompletionMenu
    ui.note('and the slash menu opens above the tail, beside them')
    ui.buf.text = '/'
    ui.complete = CompletionMenu(ui.buf, sorted(f'/{n}' for n in ui.agent.commands()),
                                 start=0, show=14)
    ui.paint(); snap('a-slash-menu-open')
    ui.complete, ui.buf.text = None, ''
    ui.paint(); snap('menu-closed')

    for i in range(8): ui.say(f'and the transcript keeps going: line {i}', 'note')
    ui.paint(); snap('half-scrolled')
    for i in range(40): ui.say(f'and it keeps going: line {i}', 'note')
    ui.paint(); snap('scrolled-away')

    print(f'\n{len(ui.pics)} picture(s) still on screen; '
          f'saved {sorted(p.name for p in Path("media").glob("*"))} in {Path.cwd()}')
    tty.close()
    return shots


if __name__ == '__main__':
    where = Path(sys.argv[1] if len(sys.argv) > 1 else 'media/streaming-images').resolve()
    asyncio.run(capture(where))
