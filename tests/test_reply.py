"""How a model reply is drawn: the palette, the code inside it, and the rows it does not waste.

Nothing here loads a model or touches a real terminal.
"""
import io

from rich.console import Console

from ramabana import cli


def rows(renderable, width=44):
    con = Console(file=io.StringIO(), width=width, force_terminal=False, no_color=True)
    con.print(renderable)
    return con.file.getvalue().splitlines()


def test_a_fenced_code_block_draws_under_every_theme(monkeypatch):
    for name in cli.THEMES:
        monkeypatch.setattr(cli, 'ACTIVE_THEME', name)
        drawn = rows(cli.Reply('```python\nx = 1\n```\n'), 40)
        assert any('x = 1' in r for r in drawn), (name, drawn)


def test_a_blank_line_inside_a_fence_is_left_alone():
    "Joining lines inside code would change the code."
    src = '```python\ndef f():\n\n    return 1\n```\n'
    assert cli.compact_md(src) == src


def test_a_paragraph_after_a_list_stays_its_own_paragraph():
    """A list straight under its lead line counted as part of that prose block, so the blank line after the
    list became a hard break and the next paragraph drew as a continuation of the last item."""
    src = 'Commits are pushed:\n- one.\n- two.\n\nRelease. The notes are out.\n\nAfter. More.'
    drawn = rows(cli.Reply(cli.compact_md(src)), 60)
    assert any(r.startswith('Release.') for r in drawn) and any(r.startswith('After.') for r in drawn), drawn


def test_the_plan_never_covers_the_end_of_the_reply(tmp_path):
    "The plan was drawn over the bottom of the transcript, so a turn that kept a plan hid its own last lines."
    import asyncio
    from rich.text import Text
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.testing import fake_agent
    a, _ = fake_agent(cfg=tmp_path)
    for i in range(14): a.plan.add(f'step {i}')
    async def go(height):
        tty = EmuTty(80, height)
        comp = Compositor(tty)
        comp._register_signals = lambda: None
        await comp.start()
        ui = cli.Ui(comp, a, loop=asyncio.get_running_loop())
        ui.show_plan, ui.hint = True, 'THE TAIL'
        for i in range(30): ui.say(Text(f'reply line {i}'), 'reply', fold=None)
        ui.say(Text('THE LAST LINE'), 'reply', fold=None)
        ui.paint()
        try:
            screen = tty.term.text()
            assert 'THE LAST LINE' in screen and 'THE TAIL' in screen and 'step 0' in screen, screen
            ui.menu = 'a menu'
            assert ui._plan_rows([]) == [], 'an open menu sits by the composer, so the plan steps aside'
        finally: comp.stop()
    for height in (20, 12): asyncio.run(go(height))   # a short screen gives the plan only the rows it can spare


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
