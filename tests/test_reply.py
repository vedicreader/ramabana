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
    import fastpylight
    assert set(cli.THEMES) <= set(cli.HL_THEMES) and set(cli.HL_THEMES.values()) <= set(fastpylight.themes())


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


def test_a_diff_is_coloured_by_line_its_code_by_language_and_anything_else_stays_gray():
    G = cli.GRUVBOX
    def at(t, i): return ' '.join(str(s.style) for s in t.spans if s.start <= i < s.end)
    d = cli.diff_rich('--- a/x.py\n+++ b/x.py\n@@ -1 +1,2 @@\n-def f(): pass\n+def f(): return 1\n+s = "café 🐍"; n = 7\n'
                      '--- a/uv.lock\n+++ b/uv.lock\n@@ -1 +1 @@\n-a = 1\n+a = 2')
    p = d.plain
    assert G['red'] in at(d, p.index('-def')) and G['green'] in at(d, p.index('+def'))
    assert cli.scope_style('keyword') in at(d, p.index('return')), 'the code on a + line is highlighted as Python'
    assert cli.scope_style('number') in at(d, p.index('7')), 'offsets past a non-ASCII character still line up'
    assert 'bold' in at(d, p.index('--- a/uv.lock')), 'the hunk ends where its header says, not at the next file'
    assert G['green'] in at(d, p.index('a = 2')) and G['red'] in at(d, p.index('a = 1')), 'no grammar: whole lines coloured'
    stat = cli.diff_rich(' leela/app.py | 24 ++++--\n 1 file changed')
    assert any(G['green'] in str(s.style) and set(stat.plain[s.start:s.end]) == {'+'} for s in stat.spans)
    assert any(G['red'] in str(s.style) and set(stat.plain[s.start:s.end]) == {'-'} for s in stat.spans)
    for s in ('3 passed in 0.2s', '--- notes\n+++ more\n- a list item'):
        out = cli.diff_rich(s)
        assert out.plain == s and not out.spans and G['gray'] in str(out.style)


def test_the_changed_table_shows_the_largest_files_and_totals_every_one():
    out = '\n'.join(rows(cli.changed_table([(f'd/f{i}.py', i, 1, i == 14) for i in range(15)]), width=60))
    assert 'd/f14.py' in out and 'd/f3.py' in out and 'd/f2.py' not in out
    assert '3 more files' in out and 'new' in next(l for l in out.splitlines() if 'd/f14.py' in l)
    assert '15 files' in out and '+105' in out and '-15' in out



def test_the_changed_table_prints_a_path_with_brackets_as_written():
    out = '\n'.join(rows(cli.changed_table([('app/[id]/page.tsx', 1, 0, False), ('x[/].py', 2, 1, True)]), width=60))
    assert 'app/[id]/page.tsx' in out and 'x[/].py' in out


def colours(md, word):
    "The colours `word` is drawn in when `md` renders as a reply."
    from rich.style import Style
    con = Console(file=io.StringIO(), width=60, force_terminal=True, color_system='truecolor')
    segs = list(con.render(cli.Reply(md)))
    return {s.style.color for s in segs if s.style and word in s.text}, Style.parse(cli.scope_style('keyword')).color

def test_a_diff_fence_highlights_the_code_in_its_hunks():
    got, kw = colours('```diff\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-def f(): pass\n+def f(): return 1\n```\n', 'return')
    assert kw in got, 'the keyword on a + line takes the palette colour, not only green'

def test_a_python_fence_is_coloured_by_fastpylight(monkeypatch):
    seen = []
    def spy(code, lang): seen.append(lang); return hl(code, lang)
    hl = cli.hl_text
    monkeypatch.setattr(cli, 'hl_text', spy)
    got, kw = colours('```python\ndef f(): return 1\n```\n', 'return')
    assert seen == ['python'] and kw in got

def test_an_unknown_fence_language_falls_back_to_pygments(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, 'hl_text', lambda code, lang: seen.append(lang))
    out = '\n'.join(rows(cli.Reply('```nosuchlang\nsome words\n```\n')))
    assert 'some words' in out and seen == []

def test_highlighting_stays_on_its_token_after_a_crlf():
    t = cli.hl_text('x = 1\r\ny = 22\r\n', 'python')
    assert t.plain == 'x = 1\ny = 22\n'
    assert any(t.plain[s.start:s.end] == '22' and s.style == cli.scope_style('number') for s in t.spans)
