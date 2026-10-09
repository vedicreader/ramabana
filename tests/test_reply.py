"""How a model reply is drawn: the palette, the code inside it, and the rows it does not waste.

Nothing here loads a model or touches a real terminal.
"""
import io

from pygments.styles import get_style_by_name
from rich.console import Console

from ramabana import cli


def rows(renderable, width=44):
    con = Console(file=io.StringIO(), width=width, force_terminal=False, no_color=True)
    con.print(renderable)
    return con.file.getvalue().splitlines()


def test_every_palette_names_a_pygments_style_that_exists():
    """`code_theme` falls back rather than raising, so a typo here would be invisible: the reply
    would just quietly highlight in the wrong scheme."""
    assert set(cli.THEMES) <= set(cli.CODE_THEMES), 'a palette with no code theme'
    for name, style in cli.CODE_THEMES.items():
        assert name in cli.THEMES, f'{name!r} is a code theme for no palette'
        get_style_by_name(style)          # raises for a style pygments does not ship
    import fastpylight
    assert set(cli.THEMES) <= set(cli.HL_THEMES) and set(cli.HL_THEMES.values()) <= set(fastpylight.themes())


def test_a_blank_line_inside_a_fence_is_left_alone():
    "Joining lines inside code would change the code."
    src = '```python\ndef f():\n\n    return 1\n```\n'
    assert cli.compact_md(src) == src


def test_a_code_block_never_renders_wider_than_the_room_it_was_given():
    """The block carries its own horizontal padding, so a long line has to wrap inside the width
    rather than push the transcript out. One column over and every reply reflows for good."""
    long = "x = 'a' * 10  # a comment long enough to need wrapping at this width\n"
    for width in (30, 44, 80):
        drawn = rows(cli.Reply(cli.compact_md(f'```python\n{long}```\n')), width)
        assert drawn, 'something was drawn'
        assert max(len(r) for r in drawn) <= width, f'overflowed {width}'


def test_compacting_changes_what_is_drawn_and_not_what_is_copied():
    """`/copy`, `y` and the notebook log read `blk.source`. Rendering is the only thing compaction
    is allowed to touch, so the text a person takes away is still the text the model sent."""
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.testing import fake_agent

    tty = EmuTty(60, 20)
    comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    ui = cli.Ui(comp, agent)
    said = 'One paragraph.\n\nAnd another.\n'
    try:
        blk = ui.stream(None, said)
        ui.flush_stream()
        assert blk.source == said, 'the raw text, blank row and all'
        assert ui._reply == said
        assert 'One paragraph.' in ui.transcript.block_text(blk)
    finally: tty.close()
