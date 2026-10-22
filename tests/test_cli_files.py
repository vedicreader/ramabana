"`@` in the composer: Tab completes files and folders through the host's own listing and read policy, and a folder attaches its listing."
import asyncio
import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import Ui, file_refs, file_note
from ramabana.testing import fake_agent
from ramabana.tools import LocalHost, attach_refs


@pytest.fixture(autouse=True)
def _own_sinks(monkeypatch):
    "Each `Ui` points the class-level sinks at itself; put them back after."
    from ramabana.runtime import Backend, TokenLogger
    monkeypatch.setattr(Backend, 'on_notice', None); monkeypatch.setattr(TokenLogger, 'sink', None)


@pytest.fixture
def proj(tmp_path):
    p = tmp_path/'proj'
    for f in ('src/app.py', 'src/util/helpers.py', 'docs/guide.md', 'my notes/plan one.md', 'README.md', '.env'): (p/f).parent.mkdir(parents=True, exist_ok=True); (p/f).write_text(f'# {f}\n')
    (tmp_path/'outside').mkdir(); (tmp_path/'outside'/'far.txt').write_text('far\n')
    return p


def _ui(root, **kw):
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent(LocalHost([str(root)], index=False, web=False, **kw))
    return Ui(comp, agent)


def _type(ui, text):
    for ch in text: ui.on_key(Key(ch, ch))


def _hits(ui, text):
    ui.buf.text, ui.buf.cursor = text, len(text)
    ui._refresh_complete()
    return [] if ui.complete is None else ui.complete.matches


def _notes(ui): return [b.source or '' for b in ui.comp.blocks.values()] + [str(getattr(b, 'body', '')) for b in ui.comp.blocks.values()]


def test_at_and_a_prefix_offers_matching_files_and_folders(proj):
    ui = _ui(proj)
    assert _hits(ui, 'look at @app')[0] == 'src/app.py'
    got = _hits(ui, 'look at @src')
    assert got[0] == 'src/' and 'src/util/' in got and 'src/app.py' in got
    assert _hits(ui, '@') and '.env' not in _hits(ui, '@'), 'a credential file is never offered'
    assert ui.complete.start == 1


def test_choosing_a_folder_completes_it_and_typing_narrows_inside(proj):
    ui = _ui(proj)
    _type(ui, 'see @do')
    assert ui.complete.matches == ['docs/', 'docs/guide.md'], 'the menu is up while typing, as for /commands'
    ui.on_key(Key('tab'))
    assert ui.buf.text == 'see @docs/', 'tab picks the folder'
    _type(ui, 'g')
    assert ui.complete.matches == ['docs/guide.md'], 'and typing narrows inside it'
    ui.complete = None; ui.buf.text = ui.buf.text[:-1]; ui.buf.cursor = len(ui.buf.text)
    ui.buf.text, ui.buf.cursor = 'see @src/ut', len('see @src/ut')
    ui.on_key(Key('tab'))
    assert ui.buf.text == 'see @src/util/' and ui.complete.matches == ['src/util/helpers.py'], 'a folder tab completes whole opens onto what it holds'
    assert _hits(ui, '@src/') == ['src/util/', 'src/app.py'], 'one level of the folder, folders first'
    assert _hits(ui, '@src/he') == [] and _hits(ui, '@src/util/he') == ['src/util/helpers.py']


def test_a_path_with_spaces_survives_completion_and_file_refs(proj):
    ui = _ui(proj)
    assert _hits(ui, '@my') == ['"my notes/', '"my notes/plan one.md"']
    assert _hits(ui, '@"my notes/pl') == ['"my notes/plan one.md"']
    assert file_refs('read @"my notes/plan one.md". then @src/app.py, and @"my notes/') == ['my notes/plan one.md', 'src/app.py', 'my notes/']
    assert attach_refs('@"no such pic.png"') == []


def test_an_outside_path_is_refused_with_a_reason_when_reading_is_off(proj):
    ui = _ui(proj)
    far = str(proj.parent/'outside')
    assert _hits(ui, f'@{far}/') == []
    assert _notes(ui), 'the refusal is said, with its reason'
    n = len(ui.comp.blocks); _hits(ui, f'@{far}/f')
    assert len(ui.comp.blocks) == n, 'said once, not on every keystroke'
    assert not ui.attach_file(f'{far}/far.txt').startswith('attached')


def test_an_outside_path_is_listed_when_reading_is_on(proj):
    ui = _ui(proj, read_outside=True)
    far = str(proj.parent/'outside')
    assert _hits(ui, f'@{far}/') == [f'{far}/far.txt']
    assert _hits(ui, '@../') and f'../outside/' in _hits(ui, '@../')
    assert ui.attach_file(f'{far}/far.txt').startswith('attached file far.txt')


def test_a_folder_ref_attaches_its_listing_and_the_listing_reaches_the_model(proj):
    ui = _ui(proj)
    assert ui.attach_file('src') == 'attached folder src/ (listing)'
    a = ui.attachments[-1]
    assert a.folder and 'util/' in a.data and 'app.py' in a.data
    note = file_note([a])
    assert f'<folder path="{proj/"src"}">' in note and 'app.py' in note
    assert 'credential' in ui.attach_file('.env')


def test_slash_completion_is_unchanged(proj):
    ui = _ui(proj)
    assert _hits(ui, '/hel') == ['/help']
    ui.buf.text, ui.buf.cursor, ui.complete = '', 0, None
    _type(ui, '/gui'); ui.on_key(Key('tab'))
    assert ui.buf.text == '/guide'


def test_at_in_python_mode_is_a_decorator_not_a_path(proj):
    ui = _ui(proj); ui.mode = 'python'
    assert ui._file_matches() is None and not ui._in_ref()


def test_learned_completes_its_subcommands_then_the_pending_ids(proj, tmp_path, monkeypatch):
    "`/learned diff ` offers what Dhrona has waiting, so an id need not be copied from `/learned`."
    import ramabana.learned as learned
    from ramabana.cli import LEARNED_WORDS
    ids = ['20261022-030647-3bdc9f', '20261023-010101-aaaaaa']
    monkeypatch.setattr(learned, 'pending', lambda folder: [dict(id=i) for i in ids])
    ui = _ui(proj)
    ui.agent.cfg = tmp_path/'cfg'
    assert _hits(ui, '/learned ') == list(LEARNED_WORDS) and _hits(ui, '/learned d') == ['diff']
    assert _hits(ui, '/learned diff ') == ids and _hits(ui, '/learned accept 20261023') == ids[1:]
    assert _hits(ui, '/learned on ') == [], 'on, off and status take no id'

