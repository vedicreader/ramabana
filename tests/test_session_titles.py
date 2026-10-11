"A session is saved with a title taken from its request and the folders it ran in, and a bare `--resume` lists this folder's sessions to pick from."
from ramabana.testing import fake_agent


def test_request_title_keeps_the_request_and_drops_the_harness():
    from ramabana.agent import request_title
    p = ('<user-request>\nFix a stale status bar in the terminal UI. Observed in a detached tmux session.\n</user-request>\n'
         '<system-reminder>After every tool call result, summarise.</system-reminder>')
    assert request_title(p) == 'Fix a stale status bar in the terminal UI.'
    assert request_title('just a question?') == 'just a question?'
    assert request_title('<notebook path="a.ipynb">cells</notebook>\nplot the curve') == 'plot the curve'
    long = request_title('word ' * 50)
    assert len(long) <= 81 and long.endswith('…') and not long.endswith(' …'), long
    assert request_title('') == ''
    # the index keeps a first prompt cut to 72 characters, so its closing tag is often gone
    assert request_title('<user-request> with leela, I want to be able to find files as well. And') == 'with leela, I want to be able to find files as well.'
    assert request_title('<user-request> ▌ a previous session was doing it') == 'a previous session was doing it', 'a pasted cursor glyph is not a title'


def test_a_session_is_saved_with_the_title_of_its_first_request_and_its_folders(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('<user-request>\nAdd a resume picker. It lists sessions.\n</user-request>'))
    list(a.stream('and a second turn'))
    row = next(s for s in a.sessions() if s['id'] == a.session_id)
    assert row['title'] == 'Add a resume picker.' and row['roots'] == ['/proj'], row


def test_pick_session_lists_this_folders_sessions_newest_first(tmp_path):
    from ramabana.agent import _set_session_meta
    from ramabana.cli import pick_session
    first, _ = fake_agent(cfg=tmp_path); list(first.stream('first here'))
    there, _ = fake_agent(cfg=tmp_path); list(there.stream('from elsewhere'))
    _set_session_meta(there, there.session_id, roots=['/elsewhere'])
    second, _ = fake_agent(cfg=tmp_path); list(second.stream('second here'))
    me, _ = fake_agent(cfg=tmp_path)
    shown = []
    assert pick_session(me, ask=lambda q: '', out=shown.append) == second.session_id, 'enter takes the newest'
    text = '\n'.join(shown)
    assert 'second here' in text and 'first here' in text and 'from elsewhere' not in text, text
    assert text.index('second here') < text.index('first here')
    assert pick_session(me, ask=lambda q: '2', out=lambda s: None) == first.session_id
    assert pick_session(me, ask=lambda q: 'n', out=lambda s: None) == '', 'n starts a new session'
    everywhere = []
    pick_session(me, all_folders=True, ask=lambda q: '', out=everywhere.append)
    assert 'from elsewhere' in '\n'.join(everywhere)


def test_a_session_resumed_elsewhere_gains_that_folder_and_lists_are_strictly_this_folder(tmp_path):
    "A folder with no sessions of its own lists nothing; `--all-folders` and `/sessions all` reach the rest."
    from ramabana.cli import pick_session
    from ramabana.testing import MemHost
    a, _ = fake_agent(cfg=tmp_path); list(a.stream('started in proj'))
    other = lambda: fake_agent(cfg=tmp_path, host=MemHost({'/other/b.py': 'y = 2\n'}, root='/other'))[0]
    shown = []
    assert pick_session(other(), ask=lambda q: '', out=shown.append) == '' and '--all-folders' in '\n'.join(shown), shown
    elsewhere = other()
    assert 'no saved sessions' in elsewhere.command('/sessions') and a.session_id in elsewhere.command('/sessions all')
    elsewhere.resume_session(a.session_id, keep_model=True)
    list(elsewhere.stream('continued in other'))
    roots = next(s for s in elsewhere.sessions() if s['id'] == a.session_id)['roots']
    assert set(roots) == {'/proj', '/other'}, roots
    assert pick_session(other(), ask=lambda q: '', out=lambda s: None) == a.session_id, 'now it ran here too'


def test_a_title_the_model_wrote_is_cleaned_and_one_the_person_set_is_kept(tmp_path):
    from ramabana.agent import _set_session_meta, model_title
    assert model_title('**Conversation Title:** Local Server Status at http://127.0.0.1:5010/ --- I am an AI language model and') == 'Local Server Status at http://127.0.0.1:5010/'
    assert model_title('**Title:** Model Auto-Discovery & Leela Integration ---') == 'Model Auto-Discovery & Leela Integration'
    assert model_title('"Fixing the status bar"') == 'Fixing the status bar'
    for fine in ('Node.js vs. Deno comparison', 'Fix *args and **kwargs handling', 'Rate-limit design'):
        assert model_title(fine) == fine, fine
    long = model_title('word ' * 50)
    assert len(long) <= 80 and model_title(long) == long, 'cleaning a clean title changes nothing'
    a, _ = fake_agent(cfg=tmp_path); list(a.stream('first request'))
    _set_session_meta(a, a.session_id, title='**Title:** Tidy the picker --- Sure, here is', manual=False)
    assert a.sessions()[0]['title'] == 'Tidy the picker'
    a.set_title('**my** own --- title')
    assert a.sessions()[0]['title'] == '**my** own --- title', 'a title the person set is shown as set'


def test_an_index_written_before_titles_were_whole_is_rebuilt_from_the_log(tmp_path):
    "The index once kept the first prompt cut to 72 characters, wrapper included, so titles stopped mid-word."
    from ramabana.agent import _session_rows, _set_session_meta, _write_session_rows
    b, _ = fake_agent(cfg=tmp_path); list(b.stream('another'))
    b.set_title('kept as set'); _set_session_meta(b, b.session_id, roots=['/proj', '/x'])
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('<user-request>\nwith leela, I want to be able to find files as well. And more.\n</user-request>'))
    old = {sid: {k: v for k, v in r.items() if k != 'first_title' and not (sid == a.session_id and k == 'title')}
                | {'version': 2, 'first_prompt': '<user-request> with leela, I want to be able to find fi'}
           for sid, r in _session_rows(a).items()}
    _write_session_rows(a, old)
    rows = {s['id']: s for s in a.sessions()}
    assert rows[a.session_id]['title'] == 'with leela, I want to be able to find files as well.'
    assert rows[b.session_id]['title'] == 'kept as set' and rows[b.session_id]['roots'] == ['/proj', '/x'], 'a rebuild keeps what the person set'


def test_request_text_keeps_the_last_request_a_turn_was_given():
    "The turn path reads `request_text`; the titles build on it rather than replace it."
    from ramabana.agent import request_body, request_text
    two = ['older <user-request>one</user-request>', '<user-request>\ntwo\n</user-request><system-reminder>x</system-reminder>']
    assert request_text(two) == 'two' and request_body(two) == 'two'


def _ui(agent):
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    tty = EmuTty(100, 30)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    return Ui(comp, agent), tty

def _drawn(ui, tag): return [b.source for b in ui.comp.blocks.values() if b.tag == tag]

def test_a_resumed_session_draws_its_last_turns(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    for p in ('zeroth ask', '<user-request>\nfirst ask\n</user-request>\n<system-reminder>summarise</system-reminder>', 'second ask', 'third ask'):
        list(a.stream(p))
    b, _ = fake_agent(cfg=tmp_path); b.resume_session(a.session_id, keep_model=True)
    ui, tty = _ui(b)
    ui.show_resumed(n=3)
    assert _drawn(ui, 'user') == ['first ask', 'second ask', 'third ask'], _drawn(ui, 'user')
    assert len(_drawn(ui, 'reply')) == 3 and any('1 earlier' in (s or '') for s in _drawn(ui, 'note')), list(ui.comp.blocks.values())
    tty.close(); b.release_session()
    c, _ = fake_agent(cfg=tmp_path)
    c.set_model = lambda name, job='turn': None   # `/resume` restores the session's model, and `fake` is no model `resolve` knows
    ui, tty = _ui(c)
    ui.buf.insert(f'/resume {a.session_id}'); ui.submit()
    assert _drawn(ui, 'user')[-1] == 'third ask', '/resume inside the interface draws the session too'
    tty.close()


def test_a_bare_resume_asks_to_pick():
    from ramabana.setup import PICK_SESSION, bare_resume
    assert bare_resume(['--resume']) == ['--resume', PICK_SESSION]
    assert bare_resume(['--resume', '--vault']) == ['--resume', PICK_SESSION, '--vault']
    assert bare_resume(['--resume', 'agent_x']) == ['--resume', 'agent_x']
    assert bare_resume(['--resume=agent_x', '--vault']) == ['--resume=agent_x', '--vault']
