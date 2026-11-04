r"""A breathing pixel sun for Ramabana's working band."""

from math import ceil, cos, floor, hypot, pi, sin

PALETTES = dict(
    dark=((0, (176, 86, 36)), (.25, (214, 112, 40)), (.5, (240, 165, 48)), (.78, (255, 224, 125)), (1, (255, 248, 214))),
    light=((0, (150, 60, 20)), (.25, (190, 90, 20)), (.5, (215, 135, 10)), (.78, (240, 185, 55)), (1, (255, 226, 140))))
LABELS = dict(dark='#d99a39', light='#9a5a10')
TALL = 11
MAX_COLUMNS = 25


def breath(elapsed, inhale=4, exhale=6):
    "Return the instruction and cosine-eased bloom for one breath."
    phase = elapsed % (inhale + exhale)
    if phase < inhale:
        return 'breathe in', (1 - cos(pi * phase / inhale)) / 2
    return 'breathe out', (1 + cos(pi * (phase - inhale) / exhale)) / 2


def ramp(stops, w):
    "The colour at warmth `w` between 0 (cool halo) and 1 (core), blended linearly between stops."
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if w <= b:
            f = (w - a) / (b - a)
            return '#' + ''.join(f'{round(p + (q - p) * f):02x}' for p, q in zip(ca, cb))
    return '#' + ''.join(f'{c:02x}' for c in stops[-1][1])


def style(w, bloom, theme, colors):
    "The colour for warmth `w`: a hex gradient, two named colours on a standard terminal, a mark with none."
    if colors == 'none': return '*' if w > .75 else 'o' if w > .4 else '.'
    if colors == 'standard': return 'bright_yellow' if w > .6 else 'yellow'
    return ramp(PALETTES.get(theme, PALETTES['dark']), w * (.85 + .15 * bloom))


def warmth(distance, halo):
    "1 at the centre, falling to .2 at the halo's edge and to nothing .8 pixels beyond; None past that."
    if distance <= halo: return 1 - .8 * (distance / halo) ** 1.5
    w = .2 * (1 - (distance - halo) / .8)
    return w if w >= .05 else None


def frame(elapsed, width, rows=TALL, inhale=4, exhale=6, theme='dark', colors='truecolor'):
    "Render the sun in at most `TALL - 1` art rows, then the breath instruction centred beneath it."
    if rows <= 0 or width <= 0: return []
    instruction, bloom = breath(elapsed, inhale, exhale)
    label = instruction[:width]
    ink = '' if colors == 'none' else 'yellow' if colors == 'standard' else LABELS.get(theme, LABELS['dark'])
    height = 2 * (min(rows, TALL) - 1)
    columns = min(MAX_COLUMNS, width if width % 2 else width - 1)
    if width < 20 or rows < 3:
        return [[(' ' * ((width - len(label)) // 2), ''), (label, ink)]]
    half = height / 2
    cx, cy = (columns - 1) / 2, (height - 1) / 2
    disc = half * (.15 + .25 * bloom)
    halo = disc + .13 * half
    pixels = [[None] * columns for _ in range(height)]
    for y in range(height):
        for x in range(columns):
            if (w := warmth(hypot(x - cx, y - cy), halo)) is not None: pixels[y][x] = style(w, bloom, theme, colors)
    for direction in range(8):
        angle = direction * pi / 4
        dx, dy = cos(angle), sin(angle)
        start, reach = halo + .5, halo + (.2 + .8 * bloom) * (cy - halo)
        for step in range(int(max(reach - start, 0) * 2) + 1):
            s = start + step / 2
            x, v = round(cx + dx * s), cy + dy * s
            for y in {floor(v), ceil(v)} if direction % 4 == 0 else (round(v),):
                if 0 <= x < columns and 0 <= y < height and pixels[y][x] is None:
                    pixels[y][x] = style(.28 * (1 - (s - start) / max(reach - start, 1)) + .05, bloom, theme, colors)
    result = []
    for y in range(0, height, 2):
        row = [(' ' * ((width - columns) // 2), '')]
        for x in range(columns):
            top, bottom = pixels[y][x], pixels[y + 1][x]
            if colors == 'none':
                mark = max((p for p in (top, bottom) if p), key='.o*'.index, default=' ')
                row.append((mark, ''))
            elif top and bottom: row.append(('▀', f'{top} on {bottom}'))
            elif top: row.append(('▀', top))
            elif bottom: row.append(('▄', bottom))
            else: row.append((' ', ''))
        result.append(row)
    centre = (width - columns) // 2 + columns // 2
    pad = min(max(centre - len(label) // 2, 0), width - len(label))
    return result + [[(' ' * pad, ''), (label, ink)]]


def setup(reg):
    "Register the busy-only sun band and the /sun command."
    enabled, start, restarted = True, None, False
    inhale, exhale = 4, 6

    def reset(*args):
        nonlocal start, restarted
        start, restarted = None, False

    def restart():
        nonlocal start, restarted
        start, restarted = None, True

    def draw(view):
        nonlocal start
        if not view.busy:
            reset()
            return None
        if not enabled:
            return None
        if start is None:
            busy_since = getattr(view, 'busy_since', None)
            start = view.t if restarted or busy_since is None else busy_since
        return frame(view.t - start, view.width, view.rows, inhale, exhale,
                     getattr(view, 'theme', 'dark'), getattr(view, 'colors', 'truecolor'))

    def command(agent, arg):
        nonlocal enabled, inhale, exhale
        usage = 'Usage: /sun [on|off|pace IN OUT] (each duration: 2 to 12 seconds)'
        parts = arg.split()
        if parts in (['on'], ['off']):
            enabled = parts[0] == 'on'
            restart()
        elif len(parts) == 3 and parts[0] == 'pace':
            try:
                new_in, new_out = map(float, parts[1:])
            except ValueError:
                return usage
            if not (2 <= new_in <= 12 and 2 <= new_out <= 12):
                return usage
            inhale, exhale = new_in, new_out
            restart()
        elif parts:
            return usage
        reg.redraw()
        return f'Sun {"on" if enabled else "off"}; inhale {inhale:g}s, exhale {exhale:g}s; period {inhale + exhale:g}s.'

    reg.band(draw, rows=TALL)
    reg.command('sun', command, 'Show sun state, toggle on/off, or set pace IN OUT.')
    for event in ('after_turn', 'stop', 'session_end'):
        reg.on(event, reset)
