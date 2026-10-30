"The `now` pane: what a turn and its sub-agents are doing, as a file, and that file drawn."

import json, re, time
from rich.console import Console

from ramabana.pane import Viewer, background_rows, now_snapshot, render
from ramabana.runtime import current_run
from ramabana.testing import MemHost, ScriptedBackend, Step, fake_agent

READ = ('view_file', {'path': '/proj/a.py'})
ASK = ('delegate_search', {'questions': ['what does a.py define?']})


def _delegating(a, seen, ask=ASK, reads=1, after=()):
    "A turn backend whose sub-agents read a file, snapshotting the agent the moment a sub-agent read starts."
    def peek(act):
        if act.run_id and not act.done and current_run().kind != 'root': seen.append(now_snapshot(a))
    a.activity.on_change = peek
    class Root(ScriptedBackend):
        def spawn(self, sp='', tools=(), **kw):
            return ScriptedBackend(self.spec, steps=[Step(tool=READ)] * reads + [Step('a() is defined\nstate: completed')], token_delay=0, tools=tools)
    be = Root(steps=[Step(tool=READ), Step(tool=ask), *after, Step('done')], token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    return be


def _text(snap, width=40, now=None, open=()):
    con = Console(record=True, width=width, color_system=None)
    con.print(render(snap, width, now=now, open=open))
    return con.export_text()


def test_a_snapshot_follows_a_read_only_sub_agent_and_forgets_it_at_the_next_turn():
    a, _ = fake_agent()
    seen = []
    be = _delegating(a, seen)
    list(a.stream('go'))
    mid = seen[0]
    assert mid['busy'] and mid['root']['state'] == 'running'
    assert mid['root']['steps'] == 2, 'the read and the delegate; the sub-agent read is not a root step'
    assert mid['root']['current'].startswith('Delegate')
    sub, = mid['subs']
    child = a.run().children[0]
    assert (sub['id'], sub['state'], sub['steps']) == (child.id, 'running', 1)
    assert sub['current'] and sub['question'].startswith('what does a.py define?')
    read, = [x for x in a.activity.since() if x.run_id == child.id]
    delegate, = [x for x in a.activity.since() if x.tool == 'delegate_search']
    assert read.parent_action_id == delegate.id, 'it still folds under the delegate call'
    assert read.dict()['run_id'] == child.id
    json.dumps(mid)

    after = now_snapshot(a)
    assert not after['busy'] and after['root']['current'] == ''
    assert [s['state'] for s in after['subs']] == ['completed'], 'a finished sub-agent stays until the next turn'
    be.steps = [Step('ok')]
    list(a.stream('again'))
    assert now_snapshot(a)['subs'] == []


def _board(now, at=None):
    "A busy turn written at `at`: a status line, a plan, two sub-agents, two files and a shell."
    call = lambda line, ok=True, done=True, out='': {'line': line, 'ok': ok, 'done': done, 'out': out}
    return {'at': now if at is None else at, 'busy': True,
            'root': {'turn_elapsed': 42, 'steps': 7, 'state': 'running', 'status': 'Checking the pane tests', 'current': 'Run shell: pytest'},
            'plan': [{'text': 'Read the viewer', 'status': 'done'}, {'text': 'Rewrite render', 'status': 'active'},
                     {'text': 'Wire the CLI', 'status': 'pending'}, {'text': 'Poll the file', 'status': 'cancelled'}],
            'subs': [{'id': 'run_aaa', 'question': 'which files import fastllm and why?', 'elapsed': 12, 'state': 'running', 'steps': 3,
                      'status': 'Searching for imports', 'current': 'Search code: fastllm',
                      'calls': [call('Search code: import fastllm', out='ramabana/agent.py:12: import fastllm'),
                                call('Read ramabana/llm.py', ok=False, out='no such file'), call('Search code: fastllm', None, False)],
                      'answer': ''},
                     {'id': 'run_bbb', 'question': 'is the pane tested?', 'elapsed': 8, 'state': 'completed', 'steps': 1, 'status': '',
                      'current': '', 'calls': [call('Read tests/test_pane.py', out='def test_render')],
                      'answer': 'Yes: tests/test_pane.py covers render and the snapshot.'}],
            'files': [{'path': 'ramabana/pane.py', 'added': 120, 'removed': 40,
                       'diff': '--- a/ramabana/pane.py\n+++ b/ramabana/pane.py\n@@ -1,3 +1,3 @@\n import json\n-from rich.live import Live\n+from teleprint.keys import Parser'},
                      {'path': 'tests/test_pane.py', 'added': 30, 'removed': 5, 'diff': '+x = 1'}],
            'background': [{'kind': 'shell', 'id': 'cmd_1234abcd', 'label': 'pytest -x tests', 'state': 'running', 'elapsed': 30},
                           {'kind': 'watch', 'id': 'w_1', 'label': '/proj', 'state': 'watching', 'elapsed': None}]}


def test_sub_agent_calls_spend_neither_the_root_budget_nor_its_hooks():
    for writes in (False, True):
        a, _ = fake_agent(max_tool_calls=20)
        a.subagent_writes, hooked = writes, []
        a.registry.on('before_tool', lambda agent, name, args: hooked.append(current_run().kind))
        be = _delegating(a, [], ('delegate_search', {'questions': ['what does a.py define?', 'who imports it?', 'is it tested?'], 'writes': writes}),
                         reads=8, after=[Step(tool=READ)])
        list(a.stream('go'))
        results = [m['content'] for m in be.hist_ if m['role'] == 'tool']
        assert 'def a' in results[-1], f'24 sub-agent reads refused the root its last read (writes={writes})'
        assert set(hooked) == ({'root', 'child'} if writes else {'root'}), 'read-only sub-agent calls are for display only'


def test_background_lists_delegations_shells_and_folder_watches(monkeypatch):
    from ramabana.monitor import FolderWatch
    a, _ = fake_agent()
    _delegating(a, [], ('delegate_async', {'question': 'what does a.py define?'}))
    list(a.stream('go'))
    end = time.monotonic() + 5
    while time.monotonic() < end and not all(r.terminal for r in a._side_runs()): time.sleep(.01)
    act = a.activity.start('run_shell_bg', {'command': 'pytest -x tests'})
    a.activity.finish(act, "started cmd_1234abcd; read it with shell_output('cmd_1234abcd')")
    gone = a.activity.start('run_shell_bg', {'command': 'forgotten'})
    a.activity.finish(gone, "started cmd_00000000; read it with shell_output('cmd_00000000')")
    def out(rid, tail=200):
        if rid != 'cmd_1234abcd': raise KeyError(rid)
        return 'running', 'collected 12 items\n3 passed'
    monkeypatch.setattr(a.host, 'cmd_output', out, raising=False)
    w = FolderWatch('/proj', 'review it'); a.monitors.watches[w.id] = w
    bg = now_snapshot(a)['background']
    assert all({'kind', 'id', 'label', 'state', 'elapsed', 'started', 'detail'} <= set(r) for r in bg)
    kinds = {r['kind']: r for r in bg}
    assert set(kinds) == {'delegate', 'shell', 'watch'}, 'a shell the host no longer knows is left out'
    assert kinds['delegate']['state'] == 'completed' and kinds['delegate']['label'].startswith('what does a.py')
    assert (kinds['shell']['id'], kinds['shell']['label'], kinds['shell']['state']) == ('cmd_1234abcd', 'pytest -x tests', 'running')
    assert kinds['watch']['id'] == w.id and '/proj' in kinds['watch']['label']
    assert kinds['shell']['detail'].endswith('3 passed') and 'all files · 0 reviews' == kinds['watch']['detail'], 'a row opens to what it has to show'
    assert now_snapshot(a)['subs'][0]['id'] == kinds['delegate']['id'], 'a background delegation is a sub-agent too'
    json.dumps(bg)
    at = time.time()
    monkeypatch.setattr(time, 'time', lambda: at)
    assert background_rows(a) == now_snapshot(a)['background'], 'the task list and the pane read one source'


def test_changes_survive_a_tool_thread_adding_to_before():
    import sys, threading
    a, _ = fake_agent()
    stop, was = threading.Event(), sys.getswitchinterval()
    def grow():
        i = 0
        while not stop.is_set():
            a.before[f'/proj/n{i % 400}.py'] = ''; a.before.pop(f'/proj/n{(i + 200) % 400}.py', None); i += 1
    sys.setswitchinterval(1e-6)   # switch threads often enough that the race shows every run
    t = threading.Thread(target=grow, daemon=True); t.start()
    try:
        for _ in range(300): a.changes()
    finally: stop.set(); t.join(); sys.setswitchinterval(was)


def test_notes_fold_to_a_line_each_and_the_newest_starts_open():
    now = time.time()
    old, new = {'at': now - 60, 'text': 'Reading the loader first, because it decides which model takes the turn.'}, \
               {'at': now, 'text': 'The loader picks the model from the routing table, so the tests go next.'}
    snap = {**_board(now), 'notes': [old, new]}
    def notes(open=()):
        rows = _text(snap, width=40, now=now, open=open).splitlines()
        return rows[rows.index('Notes') + 1:]
    shut = notes()
    assert 'routing' in ' '.join(shut[:4]), 'the newest is open, wrapped to the pane'
    assert 'decides which model' not in ' '.join(shut), 'an older note is one clipped line'
    both = notes(open={('note', old['at'])})
    assert 'decides which model' in ' '.join(both), 'opening an older note shows all of it'
    assert 'routing' not in ' '.join(notes(open={('note', new['at'])})), 'and the newest closes like any other row'
    assert 'Notes' not in _text(_board(now), now=now), 'a snapshot without notes draws no section'


def test_a_background_row_opens_to_its_output_review_or_sub_agent():
    now = time.time()
    snap = _board(now)
    snap['background'] = [{'kind': 'shell', 'id': 'cmd_1234abcd', 'label': 'pytest -x tests', 'state': 'running', 'elapsed': 30, 'detail': 'collected 12 items\n3 passed'},
                          {'kind': 'watch', 'id': 'w_1', 'label': '/proj', 'state': 'ok', 'elapsed': None, 'detail': 'all files · 1 review\nlooks fine'},
                          {'kind': 'delegate', 'id': 'run_bbb', 'label': 'is the pane tested?', 'state': 'completed', 'elapsed': 8, 'detail': ''}]
    shut = _text(snap, width=60, now=now)
    assert '3 passed' not in shut and 'looks fine' not in shut, 'rows start shut'
    opened = _text(snap, width=60, now=now, open={('bg', 'cmd_1234abcd'), ('bg', 'w_1'), ('bg', 'run_bbb')})
    assert '3 passed' in opened and 'looks fine' in opened
    assert opened.count('Yes: tests/test_pane.py covers render') == 1, 'a delegation opens to its sub-agent detail; its sub-agent row stays shut'


def test_a_background_command_logs_instead_of_splitting_the_chat(tmp_path):
    "Each `run_shell_bg` split a tmux pane under the chat; four at once squeezed it out of view."
    from ramabana.vault import WorkspaceHost
    h = WorkspaceHost([str(tmp_path)])
    h._pane = object()                      # inside tmux: splitting this would raise
    rid = h.run_cmd_bg('echo hi; read x || echo no-terminal')
    end = time.monotonic() + 10
    while h.cmd_output(rid)[0] == 'running' and time.monotonic() < end: time.sleep(.05)
    state, out = h.cmd_output(rid)
    assert state == 'exit 0' and out.split() == ['hi', 'no-terminal'], (state, out)   # its stdin is not the terminal
    h.close()


class Tty:
    "The pane's terminal: scripted input chunks, a size, and every write kept."
    def __init__(self, *input, size=(40, 30)): self.input, self.size, self.writes, self.restored = list(input), size, [], False
    def read(self, timeout=0):
        x = self.input.pop(0) if self.input else b''
        return x.encode() if isinstance(x, str) else x
    def write(self, s): self.writes.append(s)
    def restore(self): self.restored = True

def _viewer(tmp_path, snap, **kw):
    (p := tmp_path/'now.json').write_text(json.dumps(snap))
    v = Viewer(p, Tty(**kw))
    v.tick()
    return v, p

def _feed(v, *data):
    v.tty.input += data
    for _ in data: v.tick()


def test_a_shell_row_opens_to_its_command_and_p_follows_it_in_a_pane(tmp_path, monkeypatch):
    import ramabana.pane as pane
    now = time.time()
    cmd = 'uv run --env-file .env-dev --env-file /tmp/nosync.env vr-meaning cat=kaappiyam shard=0,4 usage=on'
    snap = {**_board(now), 'background': [{'kind': 'shell', 'id': 'cmd_1', 'label': cmd[:40], 'state': 'running', 'elapsed': 5,
                                           'detail': f'$ {cmd}\n(no output yet)', 'log': str(tmp_path/'cmd_1.log')}]}
    opened = _text(snap, width=50, now=now, open={('bg', 'cmd_1')})
    assert 'usage=on' in opened and '(no output yet)' in opened, 'the full command wraps rather than being cut'
    ran = []
    monkeypatch.setattr(pane.subprocess, 'Popen', lambda args, **kw: ran.append(args))
    v, _ = _viewer(tmp_path, snap)
    v.tick(now=now)
    _feed(v, 'G', 'p')
    assert ran and ran[0][:2] == ['tmux', 'split-window'] and str(tmp_path/'cmd_1.log') in ran[0][-1], ran

def _click(v, key):
    y = next(i for i, (k, _) in enumerate(v.rows) if k == key)
    _feed(v, f'\x1b[<0;3;{y + 1}M')


def test_a_click_aims_the_terminal_through_the_talk_mark_and_opens_the_transcript_left_of_the_chat(tmp_path):
    "Clicking `main` writes `main`; clicking a sub-agent leaves the talk mark alone and splits its log left of the chat pane, once."
    from ramabana.pane import talk_mark
    from test_pane_close import FakeTmux
    now, log = time.time(), tmp_path/'run_aaa.log'
    snap = {**_board(now), 'target': 'main', 'chat_pane': '%7'}
    snap['subs'][0]['log'] = str(log)
    assert '→ main' in _text(snap, now=now) and '→ ▸ run_aaa' in _text({**snap, 'target': 'run_aaa'}, now=now)
    v, p = _viewer(tmp_path, snap)
    v.tmux = tmux = FakeTmux('%7')
    assert next(k for k, _ in v.rows if k) == ('main', 'main'), 'main is the first row with a key'
    _click(v, ('main', 'main'))
    assert talk_mark(p).read_text() == 'main' and tmux.ran('split-window') == []
    talk_mark(p).unlink()   # as the CLI does once it has read it
    _click(v, ('sub', 'run_aaa'))
    assert not talk_mark(p).exists(), 'the main prompt stays aimed where it was'
    (cmd,) = tmux.ran('split-window')
    assert cmd[:5] == ('split-window', '-h', '-b', '-P', '-F') and cmd[-2] == '%7' and str(log) in cmd[-1]
    _click(v, ('sub', 'run_aaa'))
    assert len(tmux.ran('split-window')) == 1, 'its transcript is already open'


def test_after_a_sub_agent_click_the_main_prompt_talks_to_main_and_the_transcript_pane_to_the_sub_agent(tmp_path):
    "A click on a sub-agent row used to aim the main prompt at it, so a line typed in the main pane went to the sub-agent. The click opens its transcript pane, a line typed there reaches the sub-agent through the session's control socket, and the main prompt still runs the main agent."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana import cli
    from ramabana.agent import _run_store
    from ramabana.pane import Follower
    from ramabana.runtime import Run
    from test_pane_close import FakeTmux
    from test_peers import _cfg, _until
    agent, be = fake_agent(cfg=_cfg(), replies=['from main'])
    kid = Run('run_kid123', 'background', 'survey', log=agent.runs_dir/'run_kid123.log')
    _run_store(agent)[kid.id] = kid
    tty = EmuTty(80, 24)
    comp = Compositor(tty); comp._register_signals = lambda: None
    async def go():
        await comp.start()
        u = cli.Ui(comp, agent, loop=asyncio.get_running_loop())
        ctl = cli.start_control(u)
        def listed():
            "The session's own snapshot, with `kid` listed as `now_snapshot` lists a running sub-agent."
            u.write_now(force=True)
            sub = {**_board(time.time())['subs'][0], 'id': kid.id, 'log': str(kid.log)}
            p.write_text(json.dumps({**json.loads(p.read_text()), 'chat_pane': '%7', 'subs': [sub]}))
        try:
            p = cli._now_file(agent)
            listed()
            v = Viewer(p, Tty()); v.tmux = FakeTmux('%7'); v.tick()
            _click(v, ('sub', kid.id))
            assert v.pane['run'] == kid.id, 'the click opens its transcript pane'
            u.poll_talk()
            u.buf.insert('a line for main')
            if (turn := u.submit()) is not None: u.start_turn(turn)
            await _until(lambda: u.turn is None and be.sent, 'the main turn')
            assert 'a line for main' in str(be.sent[0]) and kid.drain_inbox() == []
            listed()
            f = Follower(kid.log, p)
            f.tick(40)
            await asyncio.to_thread(f.feed, b'look at b.py too\r')
            assert kid.drain_inbox() == ['look at b.py too'] and f.buf.text == '', f.said
        finally: ctl.close()
    try: asyncio.run(go())
    finally: tty.close()


def _sgr(colour, layer=38):
    "The truecolor SGR parameters that set `colour` as the foreground (38) or the background (48)."
    return f'{layer};2;' + ';'.join(str(int(colour[i:i + 2], 16)) for i in (1, 3, 5))


def _ansi(t, width=80):
    con = Console(width=width, force_terminal=True, color_system='truecolor', highlight=False)
    with con.capture() as cap: con.print(t)
    return cap.get()


def test_the_board_and_a_transcript_paint_in_the_palette_the_snapshot_carries(tmp_path):
    "A snapshot written with a light palette draws the board on its background in its colours, and so does a transcript; without a palette both stay github-dark."
    from ramabana.cli import GITHUB_DARK, LIGHT
    import ramabana.pane as pane
    now = time.time()
    snap = {**_board(now), 'palette': LIGHT}
    main = next(t for k, t in pane.board(snap, 80, now) if k == ('main', 'main'))
    assert _sgr(LIGHT['blue']) in _ansi(main), 'the main row is in the light blue'
    v, _ = _viewer(tmp_path, snap, size=(80, 30))
    drawn = ''.join(v.tty.writes)
    assert _sgr(LIGHT['bg0'], 48) in drawn and _sgr(LIGHT['fg1']) in drawn, 'the viewer fills the pane with the palette'
    assert _sgr(GITHUB_DARK['blue']) not in drawn
    assert re.search(_sgr(LIGHT['gray']) + r'[;\d]*m' + re.escape(pane.HINT[:10]), drawn), 'a gray row keeps its gray on the filled background'
    line = pane.transcript_ansi(['12:00:01 < view_file ERR no such file'], LIGHT, 40)
    assert all(_sgr(c, l) in line for c, l in ((LIGHT['bg0'], 48), (LIGHT['red'], 38), (LIGHT['gray'], 38))), 'a failed result is red, its time gray'
    assert _sgr(GITHUB_DARK['bg0'], 48) in pane.transcript_ansi(['12:00:01 > Read a.py'], width=40)


def test_a_transcript_pane_shows_whole_lines_and_draws_again_under_a_new_palette(tmp_path):
    "A missing log draws an empty pane; a partial line waits for its newline; a new palette in the snapshot draws every kept line again; a truncated log starts over."
    from ramabana.cli import LIGHT
    from ramabana.pane import PALETTE, Follower
    log, snap = tmp_path/'run_a.log', tmp_path/'now.json'
    f = Follower(log, snap)
    assert _sgr(PALETTE['bg0'], 48) in f.tick(40)
    log.write_text('12:00:01 > Read a.py\n12:00:02 < view_file ok de')
    out = f.tick(40)
    assert 'Read a.py' in out and 'view_file' not in out
    with log.open('a') as w: w.write('f a\n')
    assert 'view_file' in f.tick(40) and f.tick(40) == '', 'a tick with nothing new writes nothing'
    snap.write_text(json.dumps({'palette': LIGHT}))
    again = f.tick(40)
    assert _sgr(LIGHT['bg0'], 48) in again and 'Read a.py' in again and 'view_file' in again
    log.write_text('12:00:03 question: new\n')
    out = f.tick(40)
    assert 'new' in out and 'Read a.py' not in out


def test_the_files_section_lists_every_file_written_this_session():
    a, _ = fake_agent(MemHost({'/proj/a.py': 'a = 1\n', '/proj/b.py': 'b = 1\n'}))
    tools = {t.__name__: t for t in a.tools}
    a._prepare('first')
    tools['create_file']('/proj/a.py', 'a = 2\n')
    assert [f['path'] for f in now_snapshot(a)['files']] == ['a.py']
    a._prepare('second')
    tools['create_file']('/proj/b.py', 'b = 2\n')
    assert a.changes().keys() == {'/proj/b.py'}, 'a turn still owns only its own writes'
    assert sorted(f['path'] for f in now_snapshot(a)['files']) == ['a.py', 'b.py']
