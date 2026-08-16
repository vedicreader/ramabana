#!/usr/bin/env python
"""Capture the same drawing turn twice -- with the `on_media` hook and without it -- side by side.

    python scripts/capture_media_demo.py [outdir]

The model is `ramabana.testing.ScriptedBackend`, whose tool steps run the *real* tool list, so the
picture is written by the real `generate_image` with only the HTTP call stubbed; `token_delay` is
non-zero because at zero the turn finishes before the first repaint and there is no stream to film.
A frame is taken after every streamed chunk rather than on a wall clock, so the two runs produce the
same frames at the same points in the script and can be laid beside each other honestly.
"""
from __future__ import annotations

import asyncio, os, shutil, struct, subprocess, sys, zlib
from base64 import b64encode
from pathlib import Path

os.environ['TERM'] = 'xterm-256color'
os.environ['OPENAI_API_KEY'] = 'stub-key-no-request-is-made'

from PIL import Image, ImageDraw, ImageFont
from rich.text import Text
from teleprint import Compositor
from teleprint.testing import EmuTty

import ramabana.tools as tools
from ramabana.cli import Ui, run_turn, set_theme
from ramabana.testing import ScriptedBackend, Step, fake_agent

COLS, ROWS = 92, 16
CELL_W, CELL_H = 9, 18
BG, FG = (18, 18, 20), (220, 216, 208)
PALETTE = {
    0: (18, 18, 20), 1: (204, 102, 102), 2: (152, 151, 26), 3: (215, 153, 33),
    4: (69, 133, 136), 5: (177, 98, 134), 6: (104, 157, 106), 7: (168, 153, 132),
    8: (102, 92, 84), 9: (251, 73, 52), 10: (184, 187, 38), 11: (250, 189, 47),
    12: (131, 165, 152), 13: (211, 134, 155), 14: (142, 192, 124), 15: (235, 219, 178),
}
MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
MONO_BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'

STEPS = [
    Step(text='Sure -- drawing a bottle on a windowsill now. '),
    Step(tool=('generate_image', {'prompt': 'a bottle on a windowsill'})),
    Step(text='Done. I kept working for a while after writing it -- checking its size, '
               'reading it back, writing this. The picture existed on disk for every one '
               'of those words.'),
]


def png_bytes(w, h, rgb):
    "A real PNG, so `png_size` measures it and `generate_image` has something to save."
    row = bytes(rgb) * w
    raw = b''.join(b'\x00' + row for _ in range(h))
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _rgb(c, fallback=FG):
    if c is None: return fallback
    kind, val = c
    if kind == 'rgb': return tuple(val)
    if kind == 'palette': return PALETTE.get(int(val) % 16, fallback)
    return fallback


def render(term):
    img = Image.new('RGB', (COLS * CELL_W, ROWS * CELL_H), BG)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(MONO, 14)
    for y, line in enumerate(term.text().splitlines()[:ROWS]):
        for x, ch in enumerate(line[:COLS]):
            if ch == ' ': continue
            st = term.style(x, y)
            bg, fg = _rgb(st.get('bg'), BG), _rgb(st.get('fg'), FG)
            if st.get('inverse'): fg, bg = bg, fg
            if st.get('bold'): fg = tuple(min(255, c + 24) for c in fg)
            x0, y0 = x * CELL_W, y * CELL_H
            if bg != BG: draw.rectangle([x0, y0, x0 + CELL_W - 1, y0 + CELL_H - 1], fill=bg)
            draw.text((x0, y0), ch, fill=fg, font=font)
    draw.rectangle([0, 0, img.width - 1, img.height - 1], outline=(46, 46, 50))
    return img


async def capture(hook, workdir):
    "Every frame of one drawing turn. `hook=False` is the behaviour before this change."
    if workdir.exists(): shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    os.chdir(workdir)
    set_theme('dark')
    tty = EmuTty(COLS, ROWS, bg=BG)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    await comp.start()

    agent, _ = fake_agent(replies=[])
    be = ScriptedBackend(steps=STEPS, token_delay=0.03)
    be.refresh(agent.system_prompt(), agent.tools)
    agent._be = agent._be_or_none = lambda job='turn': be
    ui = Ui(comp, agent, loop=asyncio.get_running_loop())
    if not hook: agent.on_media = None      # the only difference between the two runs

    ui.say(Text('ramabana  ·  a turn that draws'), 'note', fold=None)
    ui.paint()

    frames, depth, drawn = [], [], []
    def snap():
        ui.paint()
        rows = tty.term.text().splitlines()
        depth.append(1 + max((i for i, l in enumerate(rows) if l.strip()), default=0))
        drawn.append(any(b.tag == 'note' and 'generated-' in (b.source or '')
                         for b in comp.blocks.values()))
        frames.append(render(tty.term))
    snap()

    # one frame per streamed chunk: the picture's arrival is then the only thing that can
    # differ between the two runs at any given frame
    orig_stream = ui.stream
    def stream(blk, chunk):
        out = orig_stream(blk, chunk)
        snap()
        return out
    ui.stream = stream

    await run_turn(ui, 'draw me a bottle on a windowsill')
    await asyncio.sleep(0.05)          # let any posted callback land, then settle
    for _ in range(3): snap()
    for t in list(comp._tasks): t.cancel()
    try: comp.stop()
    except Exception: pass
    return frames, max(depth), drawn


LAB_L = 'BEFORE   the picture is named when the whole turn ends'
LAB_R = 'AFTER    the picture is named as the tool writes it'


def label(text, width, colour):
    img = Image.new('RGB', (width, 34), (12, 12, 14))
    d = ImageDraw.Draw(img)
    d.text((10, 8), text, fill=colour, font=ImageFont.truetype(MONO_BOLD, 16))
    return img


def crop(frames, rows):
    "Trim the rows no frame in either run ever painted: a terminal, not a field of black."
    h = min(ROWS, rows + 1) * CELL_H
    return [f.crop((0, 0, f.width, h)) for f in frames]


def stitch(left, right, out_dir):
    "Both runs side by side, each padded with its own last frame so they end together."
    n = max(len(left), len(right))
    left = left + [left[-1]] * (n - len(left))
    right = right + [right[-1]] * (n - len(right))
    w, h = left[0].size
    gap, head = 16, 34
    lab_l, lab_r = label(LAB_L, w, (204, 102, 102)), label(LAB_R, w, (142, 192, 124))
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (a, b) in enumerate(zip(left, right)):
        canvas = Image.new('RGB', (w * 2 + gap, h + head), (12, 12, 14))
        canvas.paste(lab_l, (0, 0)); canvas.paste(lab_r, (w + gap, 0))
        canvas.paste(a, (0, head)); canvas.paste(b, (w + gap, head))
        canvas.save(out_dir / f'{i:05d}.png')
    return n


async def main(out):
    out.mkdir(parents=True, exist_ok=True)
    png = png_bytes(96, 128, (150, 120, 80))
    tools._post_image = lambda *a, **kw: [{'b64_json': b64encode(png).decode()}]
    before, d1, had1 = await capture(False, Path('/tmp/demo-before'))
    after, d2, had2 = await capture(True, Path('/tmp/demo-after'))
    before, after = crop(before, max(d1, d2)), crop(after, max(d1, d2))
    print(f'frames: before={len(before)} after={len(after)} rows={max(d1, d2)}')

    # the moment that matters: the first frame with the picture named in one run and not the other
    at = next(i for i, named in enumerate(had2) if named and not had1[i])
    print(f'named at frame {at} of {len(after)}; before names it at '
          f'{next((i for i, n in enumerate(had1) if n), None)}')
    before[at].save(out / 'mid-turn-before.png')
    after[at].save(out / 'mid-turn-after.png')
    before[-1].save(out / 'end-of-turn-before.png')
    after[-1].save(out / 'end-of-turn-after.png')

    seq = Path('/tmp/demo-seq')
    if seq.exists():
        for p in seq.glob('*.png'): p.unlink()
    n = stitch(before, after, seq)

    paced = Path('/tmp/demo-paced')
    paced.mkdir(exist_ok=True)
    for p in paced.glob('*.png'): p.unlink()
    k = 0
    src = sorted(seq.glob('*.png'))
    for i, p in enumerate(src):
        reps = 8 if i in (0, len(src) - 1) else 1     # hold the first and last beat
        for _ in range(reps):
            (paced / f'{k:05d}.png').write_bytes(p.read_bytes()); k += 1

    gif = out / 'streaming-image-demo.gif'
    subprocess.check_call(['ffmpeg', '-y', '-framerate', '10', '-i', str(paced / '%05d.png'),
                           '-vf', 'split[a][b];[a]palettegen[p];[b][p]paletteuse',
                           '-loop', '0', str(gif)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # the same pair as one still, for anywhere a GIF will not play
    a, b = Image.open(out/'mid-turn-before.png'), Image.open(out/'mid-turn-after.png')
    w, h, gap, head = a.width, a.height, 16, 34
    still = Image.new('RGB', (w * 2 + gap, h + head), (12, 12, 14))
    still.paste(label(LAB_L, w, (204, 102, 102)), (0, 0))
    still.paste(label(LAB_R, w, (142, 192, 124)), (w + gap, 0))
    still.paste(a, (0, head)); still.paste(b, (w + gap, head))
    still.save(out / 'mid-turn.png')
    print('stitched', n, 'gif', gif, gif.stat().st_size)


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/demo-out')))
