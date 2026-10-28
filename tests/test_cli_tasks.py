"The task list: ctrl+l and `/tasks` open the background shells, sub-agents and folder watches; enter opens a row and x then y stops it."
import asyncio, threading, time
from types import SimpleNamespace

from teleprint.keys import Key

from ramabana import cli
from ramabana.pane import background_rows
from test_cli_keys import _keys_scene, _screen
from test_pane import _delegating

SHELL = 'cmd_1234abcd'


def _key(name): return Key(name, name if len(name) == 1 else '')


def _busy(a, monkeypatch, log=''):
    "A finished background sub-agent, a running shell and a folder watch on `a`; returns the watch."
    from ramabana.monitor import FolderWatch
    _delegating(a, [], ('delegate_async', {'question': 'what does a.py define?'}))
    list(a.stream('go'))
    end = time.monotonic() + 5
    while time.monotonic() < end and not all(r.terminal for r in a._side_runs()): time.sleep(.01)
    act = a.activity.start('run_shell_bg', {'command': 'pytest -x tests'})
    a.activity.finish(act, f"started {SHELL}; read it with shell_output('{SHELL}')")
    monkeypatch.setattr(a.host, 'cmd_output', lambda rid, tail=200: ('running', 'collected 12 items\n3 passed'), raising=False)
    if log: monkeypatch.setattr(a.host, '_bg', {SHELL: (None, log)}, raising=False)
    w = FolderWatch('/proj', 'review it'); a.monitors.watches[w.id] = w
    return w


def _pick(u, rid):
    "Move the open task list's cursor to the row named `rid`."
    u.on_key(_key(str([r['id'] for r in u.menu.rows].index(rid) + 1)))


def _said(u): return [u.transcript.block_text(b) for b in u.comp.blocks.values()]


def test_ctrl_l_on_an_empty_composer_opens_the_task_list(monkeypatch):
    async def body(u, agent, tty):
        w = _busy(agent, monkeypatch)
        assert u.on_key(_key(cli.TASKS_KEY)) is None
        assert isinstance(u.menu, cli.TaskMenu)
        screen = _screen(u, tty)
        assert SHELL in screen and 'pytest -x tests' in screen and 'running' in screen and w.folder in screen
    _keys_scene(body)


def test_slash_tasks_opens_the_same_list(monkeypatch):
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        u.buf.insert('/tasks')
        assert u.submit() is None
        assert isinstance(u.menu, cli.TaskMenu) and any(r['id'] == SHELL for r in u.menu.rows)
        assert not any('unknown command' in t for t in _said(u))
    _keys_scene(body)


def test_the_rows_name_kind_state_and_age(monkeypatch):
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        rows = background_rows(agent)
        shell = next(r for r in rows if r['kind'] == 'shell')
        menu = cli.TaskMenu(lambda: background_rows(agent), now=lambda: shell['started'] + 125)
        text = dict(zip((r['kind'] for r in menu.rows), (r.plain for r in menu.render()[1:])))
        assert all(w in text['shell'] for w in ('shell', 'running', '2m')), text['shell']
        assert 'completed' in text['delegate'], text
        assert list(text)[-1] == 'delegate', 'running work first, finished last'
        assert cli.TaskMenu(lambda: []).choose('a') == (True, None), 'a list whose tasks all ended closes on any key'
    _keys_scene(body)


def test_with_nothing_running_ctrl_l_flashes_and_opens_nothing():
    async def body(u, agent, tty):
        u.on_key(_key('ctrl+l'))
        assert u.menu is None and 'no background tasks' in _screen(u, tty)
    _keys_scene(body)


def test_enter_opens_a_shell_in_a_pane_in_tmux_and_prints_it_outside(monkeypatch):
    opened = []
    async def in_tmux(u, agent, tty):
        _busy(agent, monkeypatch, log='/tmp/cmd_1234abcd.log')
        monkeypatch.setattr(agent.host, 'tmux_pane', SimpleNamespace(id='%1'), raising=False)
        monkeypatch.setattr(agent.host, 'open_pane', lambda cmd, title='', **kw: opened.append((cmd, title)), raising=False)
        u.on_key(_key('ctrl+l')); _pick(u, SHELL); u.on_key(_key('enter'))
        assert u.menu is None
    async def outside(u, agent, tty):
        _busy(agent, monkeypatch)
        u.on_key(_key('ctrl+l')); _pick(u, SHELL); u.on_key(_key('enter'))
        assert u.menu is None and _said(u)[-1].endswith('3 passed')
    _keys_scene(in_tmux); _keys_scene(outside)
    (cmd, title), = opened
    assert 'less -R +F' in cmd and '/tmp/cmd_1234abcd.log' in cmd and title == SHELL


def test_enter_on_a_watch_prints_its_last_review_and_on_a_finished_sub_agent_its_answer(monkeypatch):
    async def body(u, agent, tty):
        w = _busy(agent, monkeypatch)
        w.last_review = 'nothing in /proj needs review'
        u.on_key(_key('ctrl+l')); _pick(u, w.id); u.on_key(_key('enter'))
        assert u.menu is None and w.last_review in _said(u)[-1]
        run, = [r for r in agent._side_runs() if r.kind == 'background']
        u.on_key(_key('ctrl+l')); _pick(u, run.id); u.on_key(_key('enter'))
        assert run.answer and run.answer in _said(u)[-1]
    _keys_scene(body)


def test_x_asks_first_and_y_stops_the_shell_the_sub_agent_or_the_watch(monkeypatch):
    stopped, cancelled = [], []
    async def body(u, agent, tty):
        w = _busy(agent, monkeypatch)
        monkeypatch.setattr(agent.host, 'cmd_stop', lambda rid: stopped.append(rid) or 'stopped', raising=False)
        monkeypatch.setattr(agent, 'cancel', lambda rid='', grace=None: cancelled.append(rid) or {'state': 'cancelled'})
        u.on_key(_key('ctrl+l')); _pick(u, SHELL); u.on_key(_key('x'))
        asking = _screen(u, tty)
        assert isinstance(u.menu, cli.TaskMenu) and 'y stop' in asking and stopped == []
        u.on_key(_key('n'))
        assert 'y stop' not in _screen(u, tty) and u.menu.sure is None and stopped == []
        u.on_key(_key('x')); u.on_key(_key('y'))
        assert stopped == [SHELL] and u.menu is None
        run, = [r for r in agent._side_runs() if r.kind == 'background']
        u.on_key(_key('ctrl+l')); _pick(u, run.id); u.on_key(_key('x')); u.on_key(_key('y'))
        for _ in range(100):
            if cancelled: break
            await asyncio.sleep(.02)
        assert cancelled == [run.id]
        u.on_key(_key('ctrl+l')); _pick(u, w.id); u.on_key(_key('x')); u.on_key(_key('y'))
        assert w.id not in [x.id for x in agent.monitors.all()]
    _keys_scene(body)


def test_esc_returns_to_the_composer_with_the_text_intact(monkeypatch):
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        u.buf.insert('half typed')
        u.on_key(_key('ctrl+l'))
        assert isinstance(u.menu, cli.TaskMenu)
        u.on_key(_key('escape'))
        assert u.menu is None and u.buf.text == 'half typed'
    _keys_scene(body)


def test_ctrl_l_is_ignored_during_an_approval_and_in_the_transcript_view(monkeypatch):
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        u.ask = SimpleNamespace(summary='write x.py')
        u.on_key(_key('ctrl+l'))
        assert u.menu is None
        u.ask = None
        u.enter_transcript()
        u.on_key(_key('ctrl+l'))
        assert u.menu is None
        u.leave_transcript()
    _keys_scene(body)


def test_an_approval_closes_the_open_list_and_ctrl_c_closes_it_without_stopping_the_turn(monkeypatch):
    stopped = []
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        monkeypatch.setattr(agent.host, 'cmd_stop', lambda rid: stopped.append(rid), raising=False)
        u.turn = SimpleNamespace(done=lambda: False)
        u.on_key(_key('ctrl+l')); u.on_key(_key('ctrl+c'))
        assert u.menu is None and u._stop_count == 0, 'ctrl+c closes the list; the turn runs on'
        u.on_key(_key('ctrl+l')); _pick(u, SHELL); u.on_key(_key('x'))
        threading.Thread(target=lambda: agent.approvals.request('create_file', {'path': '/proj/a.md', 'text': 'x'}), daemon=True).start()
        for _ in range(50):
            await asyncio.sleep(.02)
            if u.ask is not None: break
        assert u.ask is not None and u.menu is None, 'the question takes the keys'
        ask = u.ask
        u.on_key(_key('y'))
        assert stopped == [] and ask.answer is True, 'y answered the question'
        u.turn = None
    _keys_scene(body)


def test_the_hint_row_and_the_key_card_name_ctrl_l(monkeypatch):
    async def body(u, agent, tty):
        _busy(agent, monkeypatch)
        idle = _screen(u, tty)
        u.start_turn(asyncio.sleep(.5)); running = _screen(u, tty)
        assert 'ctrl+l tasks' in idle and 'ctrl+l tasks' in running
        u.on_key(_key('ctrl+l'))
        assert 'x stops' in u.footer_hint()
    _keys_scene(body)
    assert 'ctrl+l' in cli.HELP and '/tasks' in cli.HELP