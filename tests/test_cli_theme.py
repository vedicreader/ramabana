"`auto` follows the terminal's background, and `/theme NAME --save` keeps a palette in config.toml."
import asyncio

import pytest
from teleprint.compositor import Compositor
from teleprint.testing import EmuTty

from ramabana import cli
from ramabana.setup import config_path, load_config
from ramabana.testing import fake_agent


@pytest.fixture(autouse=True)
def _default_theme():
    yield
    cli.set_theme('github-dark')


def test_auto_takes_the_background_the_terminal_reports_then_colorfgbg_then_dark(monkeypatch):
    monkeypatch.delenv('COLORFGBG', raising=False)
    assert [n for n in cli.THEMES if cli.is_light(n)] == ['light', 'gruvbox-light', 'latte', 'solarized-light']
    for bg, want in (((255, 255, 255), 'light'), ((40, 40, 40), 'github-dark')):
        with EmuTty(80, 24, bg=bg) as tty: reply = asyncio.run(cli.query_background(Compositor(tty)))
        assert cli.set_theme('auto', reply) == want, (bg, reply)
    assert cli.set_theme('auto', b'') == 'github-dark', 'no answer and no $COLORFGBG is dark'
    monkeypatch.setenv('COLORFGBG', '0;15')
    assert cli.set_theme('auto', b'') == 'light'
    monkeypatch.setenv('COLORFGBG', '15;default;0')
    assert cli.set_theme('auto', b'') == 'github-dark'
    assert cli.set_theme('auto', b'\x1b]11;rgb:ffff/ffff/ffff\x1b\\') == 'light', "the terminal's answer beats $COLORFGBG"


def test_theme_save_writes_cli_theme_and_keeps_the_rest_of_config_toml():
    p = config_path()
    p.write_text('# my settings\n[cli]\n# asks about edits only\napprove = "edits"\n')
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    agent, _ = fake_agent()
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent)
        u.buf.insert('/theme nord'); u.submit()
        assert cli.ACTIVE_THEME == 'nord' and 'theme' not in p.read_text(), 'a plain /theme lasts this session only'
        u.buf.insert('/theme gruvbox --save'); u.submit()
        assert cli.ACTIVE_THEME == 'gruvbox'
        u.buf.insert('/theme'); u.submit()
        return list(u.comp.blocks.values())[-1].source
    listed = asyncio.run(go())
    tty.close()
    text = p.read_text()
    assert '# my settings' in text and '# asks about edits only' in text, text
    assert load_config()[0] == {'cli.approve': 'edits', 'cli.theme': 'gruvbox'}
    assert '▸ gruvbox' in listed and all(n in listed for n in cli.THEMES), listed
    rows = [l.split()[-2:] for l in listed.splitlines()]
    assert ['latte', 'light'] in rows and ['nord', 'dark'] in rows, rows
