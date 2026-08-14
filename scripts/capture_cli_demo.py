#!/usr/bin/env python
"""Drive the ramabana CLI headlessly and capture PNG frames + an MP4/GIF demo."""
from __future__ import annotations

import asyncio, os, shutil, subprocess, sys
from pathlib import Path

os.environ.setdefault('RAMABANA_LITERT_BACKEND', 'cpu')
os.environ.setdefault('TERM', 'xterm-256color')

from PIL import Image, ImageDraw, ImageFont
from teleprint import Compositor
from teleprint.testing import EmuTty

from ramabana import Agent
from ramabana.cli import Ui, set_theme
from ramabana.tools import LocalHost

COLS, ROWS = 100, 28
CELL_W, CELL_H = 9, 18
BG = (18, 18, 20)
FG = (220, 216, 208)
PALETTE = {
    0: (18, 18, 20), 1: (204, 102, 102), 2: (152, 151, 26), 3: (215, 153, 33),
    4: (69, 133, 136), 5: (177, 98, 134), 6: (104, 157, 106), 7: (168, 153, 132),
    8: (102, 92, 84), 9: (251, 73, 52), 10: (184, 187, 38), 11: (250, 189, 47),
    12: (131, 165, 152), 13: (211, 134, 155), 14: (142, 192, 124), 15: (235, 219, 178),
}


def _rgb(style_color, fallback=FG):
    if style_color is None: return fallback
    kind, val = style_color
    if kind == 'rgb': return tuple(val)
    if kind == 'palette': return PALETTE.get(int(val) % 16, fallback)
    return fallback


def render_frame(term, path: Path):
    img = Image.new('RGB', (COLS * CELL_W, ROWS * CELL_H), BG)
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 14)
    except Exception: font = ImageFont.load_default()
    text = term.text()
    lines = text.splitlines()
    for y, line in enumerate(lines[:ROWS]):
        for x, ch in enumerate(line[:COLS]):
            if ch == ' ': continue
            st = term.style(x, y)
            bg = _rgb(st.get('bg'), BG)
            fg = _rgb(st.get('fg'), FG)
            if st.get('inverse'): fg, bg = bg, fg
            if st.get('bold'): fg = tuple(min(255, c + 24) for c in fg)
            x0, y0 = x * CELL_W, y * CELL_H
            if bg != BG:
                draw.rectangle([x0, y0, x0 + CELL_W - 1, y0 + CELL_H - 1], fill=bg)
            draw.text((x0, y0), ch, fill=fg, font=font)
    # soft vignette border
    draw.rectangle([0, 0, COLS * CELL_W - 1, ROWS * CELL_H - 1], outline=(40, 40, 44))
    img.save(path)
    return img


async def demo(out: Path):
    frames = out / 'frames'
    if frames.exists(): shutil.rmtree(frames)
    frames.mkdir(parents=True)
    set_theme('dark')
    tty = EmuTty(COLS, ROWS, bg=(18, 18, 20))
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    await comp.start()

    host = LocalHost(['/workspace'], web=False, index=False)
    agent = Agent(host, model='gemma-e2b', extensions=False, subagents=False)
    ui = Ui(comp, agent)
    comp.on_key = ui.on_key
    agent.start()
    ui.note(agent.note)
    ui.paint()

    shots: list[Path] = []
    def snap(tag):
        p = frames / f'{len(shots):04d}-{tag}.png'
        render_frame(tty.term, p)
        shots.append(p)
        if tag in ('ready', 'typing', 'working', 'reply', 'done'):
            shutil.copy(p, out / f'cli-{tag}.png')
        print(f'  snap {tag}: {tty.term.text().splitlines()[-1] if tty.term.text().strip() else "(blank)"}')

    snap('ready')

    prompt = 'In one short sentence, what is ramabana?'
    for i, ch in enumerate(prompt):
        comp.on_bytes(ch.encode())
        if i % 4 == 0: snap(f'type-{i:02d}')
    snap('typing')
    comp.on_bytes(b'\r')

    # Wait until the turn task finishes and a reply block appears.
    saw_working = False
    for i in range(300):
        await asyncio.sleep(0.25)
        if i % 4 == 0:
            tag = 'working' if (ui.turn is not None or not saw_working) else f'stream-{i:03d}'
            if ui.turn is not None: saw_working = True
            snap(tag if tag == 'working' and not any(p.name.endswith('-working.png') for p in shots) else f'stream-{i:03d}')
        tags = [b.tag for b in comp.blocks.values()]
        if saw_working and ui.turn is None and 'reply' in tags:
            ui.paint()
            snap('reply')
            break
    else:
        ui.paint(); snap('reply')

    # status / done
    await asyncio.sleep(0.4)
    ui.paint()
    snap('done')
    print('FINAL SCREEN:\n' + tty.term.text())

    # Build a paced sequence for video.
    seq = frames / 'seq'
    seq.mkdir(exist_ok=True)
    n = 0
    for p in shots:
        name = p.name
        if any(k in name for k in ('ready', 'typing', 'working', 'reply', 'done')): reps = 10
        elif name.startswith(tuple(f'{i:04d}-type' for i in range(50))): reps = 2
        else: reps = 1
        for _ in range(reps):
            shutil.copy(p, seq / f'{n:05d}.png'); n += 1

    mp4 = out / 'ramabana-cli-demo.mp4'
    subprocess.check_call([
        'ffmpeg', '-y', '-framerate', '8', '-i', str(seq / '%05d.png'),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '22', str(mp4)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    gif = out / 'ramabana-cli-demo.gif'
    subprocess.check_call([
        'ffmpeg', '-y', '-i', str(mp4), '-vf', 'fps=6,scale=900:-1:flags=lanczos',
        '-loop', '0', str(gif)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # keep compositor alive until after last snap; then stop
    for t in list(comp._tasks):
        t.cancel()
    await asyncio.sleep(0.05)
    try: comp.stop()
    except Exception: pass
    try: tty.close()
    except Exception: pass
    print('frames', len(shots), 'mp4', mp4.stat().st_size, 'gif', gif.stat().st_size)
    return mp4


if __name__ == '__main__':
    out = Path(sys.argv[1] if len(sys.argv) > 1 else '/workspace/media')
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(demo(out))
