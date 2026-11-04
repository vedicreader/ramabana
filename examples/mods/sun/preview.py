r"""Print evenly spaced ANSI frames from one ten-second breath."""

import argparse

from rich.console import Console
from rich.text import Text

from mod import frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=5)
    parser.add_argument('--width', type=int, default=60)
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    parser.add_argument('--colors', choices=('truecolor', '256', 'standard', 'none'), default='truecolor')
    args = parser.parse_args()
    if args.frames < 1 or args.width < 1:
        parser.error('--frames and --width must be positive')
    system = None if args.colors == 'none' else args.colors
    console = Console(color_system=system, force_terminal=True, width=args.width)
    for index in range(args.frames):
        t = 10 * index / max(1, args.frames - 1)
        console.print(f't = {t:.2f}s', markup=False, highlight=False)
        for row in frame(t, args.width, theme=args.theme, colors=args.colors):
            line = Text()
            for part, style in row:
                line.append(part, style)
            console.print(line)
        console.print()


if __name__ == '__main__':
    main()
