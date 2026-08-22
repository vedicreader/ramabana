"""How a model reply is drawn: the palette, the code inside it, and the rows it does not waste.

Nothing here loads a model or touches a real terminal.
"""
import io

import pytest
from pygments.styles import get_style_by_name
from rich.console import Console
from rich.markdown import Markdown

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


def test_the_default_is_the_near_black_github_dark():
    assert cli.ACTIVE_THEME == 'github-dark'
    assert cli.set_theme('auto') == 'github-dark', 'auto lands on the default, not on `dark`'
    assert cli.GRUVBOX['bg0'] == '#0a0c10', 'darker than GitHub\'s own #0d1117 canvas'
    assert cli.code_theme() == 'github-dark'


def test_an_unknown_theme_names_the_ones_there_are():
    with pytest.raises(ValueError) as e: cli.set_theme('githubdark')
    assert 'github-dark' in str(e.value) and 'latte' in str(e.value)
    cli.set_theme('github-dark')


def test_the_code_background_follows_the_palette_rather_than_one_colour():
    """One background cannot serve both: what reads as subtle against a near-black canvas is
    invisible on `latte`, and a pygments style's own background is whatever its author's editor was."""
    seen = {}
    for name in ('github-dark', 'latte', 'gruvbox-light'):
        cli.set_theme(name); seen[name] = cli.code_bg()
        assert seen[name] == cli.THEMES[name]['bg1']
    assert len(set(seen.values())) == 3, 'three palettes, three backgrounds'
    cli.set_theme('github-dark')


def test_two_paragraphs_lose_the_row_between_them_and_nothing_else_does():
    src = ('First paragraph here.\n\nSecond paragraph here.\n\n## Head\n\nUnder it.\n\n'
           '- one\n- two\n\n```python\ndef f(): return 1\n```\n\nLast word.\n')
    out = cli.compact_md(src)
    assert 'First paragraph here.  \nSecond paragraph here.' in out, 'joined by a hard break'
    assert '\n\n## Head' in out, 'a heading keeps its row'
    assert 'Under it.\n\n- one' in out, 'a list keeps its row'
    assert '\n\n```python' in out and '```\n\nLast word.' in out, 'a fence keeps both its rows'
    assert 'def f(): return 1' in out
    assert len(rows(cli.Reply(out))) < len(rows(Markdown(src))), 'fewer rows than Rich alone'


def test_a_blank_line_inside_a_fence_is_left_alone():
    "Joining lines inside code would change the code."
    src = '```python\ndef f():\n\n    return 1\n```\n'
    assert cli.compact_md(src) == src


def test_a_paragraph_after_a_list_is_not_pulled_into_it():
    out = cli.compact_md('- one\n- two\n\nProse after the list.\n')
    assert '- two\n\nProse after the list.' in out


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


def test_the_model_row_sits_under_the_bar_and_follows_the_routing_table():
    """`/model` mid-turn changes where the *next* turn goes, so this row reads the routing table
    rather than `agent.note`, which the backend that is running sets and only on the next turn."""
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.testing import fake_agent

    tty = EmuTty(110, 14)
    comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent()
    ui = cli.Ui(comp, agent)
    try:
        rows, _ = ui.tail()
        assert rows[1] is not ui.status(), 'a row of its own'
        assert ui.model_row().plain.strip().startswith(agent.model.name)
        assert 'ctx' in ui.model_row().plain, 'the window is what the row is for'
        assert 'tools' not in ui.model_row().plain, 'the bar above already counts them'

        # a stand-in agent, never the real class: patching `Agent.model` and deleting it again
        # removed the property outright and took fourteen unrelated tests with it
        from ramabana.core import ModelSpec

        class Held:
            def __init__(self, spec): self.model = spec
        ui.agent = Held(ModelSpec('made-up/model', 'remote', 'made-up/model', 200_000))
        assert 'made-up/model' in ui.model_row().plain, 'it followed the change'
        assert '200k ctx' in ui.model_row().plain

        class Angry:
            @property
            def model(self): raise RuntimeError('no such model')
        ui.agent = Angry()
        assert 'no such model' in ui.model_row().plain, 'an unroutable model is a sentence, not a raise'
    finally: tty.close()

