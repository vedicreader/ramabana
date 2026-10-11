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


def test_a_bare_resume_asks_to_pick():
    from ramabana.setup import PICK_SESSION, bare_resume
    assert bare_resume(['--resume']) == ['--resume', PICK_SESSION]
    assert bare_resume(['--resume', '--vault']) == ['--resume', PICK_SESSION, '--vault']
    assert bare_resume(['--resume', 'agent_x']) == ['--resume', 'agent_x']
    assert bare_resume(['--resume=agent_x', '--vault']) == ['--resume=agent_x', '--vault']
