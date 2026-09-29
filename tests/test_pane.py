"The `now` pane: what a turn and its sub-agents are doing, as a file, and that file drawn."

import json, time
import pytest
from rich.console import Console

from ramabana.pane import PALETTE, Viewer, board, now_snapshot, quit_mark, read_snapshot, render, write_snapshot
from ramabana.runtime import current_run
from ramabana.testing import ScriptedBackend, Step, fake_agent

READ = ('view_file', {'path': '/proj/a.py'})
ASK = ('delegate_search', {'questions': ['what does a.py define?']})


def _delegating(a, seen, ask=ASK, reads=1, after=()):
    "A turn backend whose sub-agents read a file, snapshotting the agent the moment a sub-agent read starts."
    def peek(act):
        if act.run_id and not act.done and current_run().kind != 'root': seen.append(now_snapshot(a))
    a.activity.on_change = peek
    class Root(ScriptedBackend):
        def spawn(self, sp='', tools=(), **kw):
            return ScriptedBackend(self.spec, steps=[Step(tool=READ)] * reads + [Step('a() is defined')], token_delay=0, tools=tools)
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


def test_each_of_several_questions_is_its_own_sub_agent_and_none_of_their_calls_is_a_root_step():
    a, _ = fake_agent()
    _delegating(a, [], ('delegate_search', {'questions': ['what does a.py define?', 'who imports a.py?']}))
    list(a.stream('go'))
    snap = now_snapshot(a)
    assert snap['root']['steps'] == 2
    assert sorted(s['steps'] for s in snap['subs']) == [1, 1]
    delegate, = [x for x in a.activity.since() if x.tool == 'delegate_search']
    reads = [x for x in a.activity.since() if x.run_id in {s['id'] for s in snap['subs']}]
    assert len(reads) == 2 and {x.parent_action_id for x in reads} == {delegate.id}


def test_a_background_delegation_is_listed_while_it_runs_and_after_it_finishes():
    a, _ = fake_agent()
    _delegating(a, [], ('delegate_async', {'question': 'what does a.py define?'}))
    list(a.stream('go'))
    end = time.monotonic() + 5
    while time.monotonic() < end and not all(r.terminal for r in a._side_runs()): time.sleep(.01)
    sub, = now_snapshot(a)['subs']
    assert sub['state'] == 'completed' and sub['steps'] == 1 and sub['question'].startswith('what does a.py')
    assert now_snapshot(a)['root']['steps'] == 2


def test_a_snapshot_is_written_whole_and_a_bad_file_reads_as_none(tmp_path):
    a, _ = fake_agent()
    p = tmp_path/'now.json'
    assert read_snapshot(p) is None
    write_snapshot(a, p)
    assert read_snapshot(p)['busy'] is False
    assert [f.name for f in tmp_path.iterdir()] == ['now.json'], 'no temporary file left behind'
    p.write_text('{"busy": tr')
    assert read_snapshot(p) is None


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

SUB, FILE = ('sub', 'run_aaa'), ('file', 'ramabana/pane.py')

def test_the_board_draws_each_section_collapsed_and_opens_a_row_on_request():
    now = time.time()
    assert 'waiting' in _text(None)
    idle = {'at': now, 'busy': False, 'root': {'turn_elapsed': 9, 'steps': 4, 'state': 'completed', 'status': '', 'current': ''},
            'plan': [], 'subs': [], 'files': [], 'background': []}
    assert _text(idle, now=now).split() == ['main', '·', 'idle', '·', '4', 'steps'], 'idle is one line; empty sections are left out'
    out = _text(_board(now, now - 5), now=now)
    head = out.splitlines()[0]
    assert 'step 7' in head and '47s' in head and 'Checking the pane' in head, 'a running clock advances past the write'
    assert 'Run shell: pytest' not in out, 'the chat shows the current call, so the board does not'
    assert all(t in out for t in ('Plan', '✓ Read the viewer', '◐ Rewrite render', '○ Wire the CLI', '✗ Poll the file'))
    rows = out.splitlines()
    aaa, bbb = [next(l for l in rows if i in l) for i in ('run_aaa', 'run_bbb')]
    assert aaa.startswith('▸ run_aaa') and 'Searching for' in aaa and aaa.rstrip().endswith('▶') and '17s' in aaa
    assert bbb.startswith('▸ run_bbb') and 'is the pane tested?' in bbb and bbb.rstrip().endswith('✓'), 'no status: the question'
    assert 'import fastllm' not in out and 'covers render' not in out, 'a closed row hides its calls and answer'
    f = next(l for l in rows if 'ramabana/pane.py' in l)
    assert f.startswith('▸') and '+120' in f and '−40' in f and 'Parser' not in out
    sh = next(l for l in rows if 'pytest -x tests' in l)
    assert 'shell' in sh and 'running' in sh and '35s' in sh
    assert 'watching' in out and all(len(l) <= 40 for l in rows), 'long lines are cut, not wrapped'

    out = _text(_board(now), now=now, open={SUB, FILE, ('sub', 'run_bbb')})
    assert '▾ run_aaa' in out and 'which files import fastllm' in out, 'the question the status line replaced'
    assert '✓ Search code: import fastllm' in out and '✗ Read ramabana/llm.py' in out and 'no such file' in out
    assert '→ Yes: tests/test_pane.py' in out and 'the snapshot.' in out, 'a finished sub-agent shows its answer, wrapped'
    assert '▾' in next(l for l in out.splitlines() if 'ramabana/pane.py' in l) and '+from teleprint.keys import Parser' in out
    assert all(len(l) <= 40 for l in out.splitlines())
    rows = dict((t.plain.strip(), t) for _, t in board(_board(now), 40, now, {FILE}))
    assert PALETTE['green'] in str(rows['+from teleprint.keys import Parser'].style) and PALETTE['red'] in str(rows['-from rich.live import Live'].style)


class Tty:
    "The pane's terminal: scripted input chunks (an exception is raised), a size, and every write kept."
    def __init__(self, *input, size=(40, 30)): self.input, self.size, self.writes, self.restored = list(input), size, [], False
    def read(self, timeout=0):
        x = self.input.pop(0) if self.input else b''
        if isinstance(x, BaseException): raise x
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

def _y(v, key): return next(i for i, (k, _) in enumerate(v.rows) if k == key)

def test_a_click_opens_the_row_under_it_and_keys_move_and_toggle(tmp_path):
    v, _ = _viewer(tmp_path, _board(time.time()))
    y = _y(v, SUB)
    _feed(v, f'\x1b[<0;3;{y + 1}M\x1b[<0;3;{y + 1}m')
    assert v.open == {SUB} and v.cursor == SUB and '▾ run_aaa' in ''.join(v.tty.writes), 'the press toggles, the release does not'
    _feed(v, f'\x1b[<0;3;{y + 1}M', '\x1b[<0;3;1M')
    assert v.open == set(), 'a second click closes it; a click on the header does nothing'
    moves = []
    for k in ('j', 'j', 'k', '\x1b[B', '\x1b[A', 'G', 'g'): _feed(v, k); moves.append(v.cursor)
    assert moves == [('sub', 'run_bbb'), FILE, ('sub', 'run_bbb'), FILE, ('sub', 'run_bbb'), ('file', 'tests/test_pane.py'), SUB]
    _feed(v, '\r'); assert v.open == {SUB}
    _feed(v, ' '); assert v.open == set()
    _feed(v, 'q'); assert v.done
    v.done = False
    _feed(v, '\x03'); assert v.done, 'ctrl+c as a byte quits too'

def test_open_rows_and_the_cursor_survive_a_new_snapshot(tmp_path):
    now = time.time()
    v, p = _viewer(tmp_path, _board(now))
    _feed(v, 'j', '\r', 'G')
    later = _board(now + 1)
    later['subs'][0]['calls'].append({'line': 'Read ramabana/fresh.py', 'ok': True, 'done': True, 'out': ''})
    p.write_text(json.dumps(later))
    v.tick()
    assert v.snap['at'] == now + 1 and v.open == {SUB} and v.cursor == ('file', 'tests/test_pane.py')
    assert 'Read ramabana/fresh.py' in ''.join(v.tty.writes)

def test_only_changed_lines_are_written_and_a_resize_repaints_all(tmp_path):
    now = time.time()
    v, _ = _viewer(tmp_path, _board(now))
    v.tick(now=now); n = len(v.tty.writes)
    v.tick(now=now)
    assert len(v.tty.writes) == n, 'nothing changed: nothing written'
    v.tick(now=now + 1)
    tick = v.tty.writes[-1]
    assert '43s' in tick and '13s' in tick and 'Rewrite render' not in tick, 'a clock second rewrites only the rows with clocks'
    v.tty.size = (50, 30)
    v.tick(now=now + 1)
    assert v.tty.writes[-1].startswith('\x1b[2J') and 'Rewrite render' in v.tty.writes[-1], 'a resize repaints every row'

def test_a_bad_frame_becomes_an_error_row_and_the_terminal_is_given_back(tmp_path):
    now = time.time()
    v, p = _viewer(tmp_path, _board(now))
    p.write_text(json.dumps({'at': now, 'busy': True, 'root': {}}))
    v.tick()
    assert 'KeyError' in v.err and v.snap['at'] == now, 'the last good snapshot stays'
    v.tick()
    assert '⚠' in v.tty.writes[-1] and _y(v, SUB), 'the next frame draws it with an error row'
    p.write_text(json.dumps(_board(now + 1)))
    v.tick()
    assert v.err == '' and v.snap['at'] == now + 1

    for stop in (b'q', KeyboardInterrupt()):
        v = Viewer(p, Tty(RuntimeError('tty hiccup'), stop))
        v.run()
        w = v.tty.writes
        assert '\x1b[?1049h' in w[0] and '\x1b[?1000;1006h' in w[0] and v.tty.input == [], 'the loop read on past the hiccup'
        assert '\x1b[?1049l' in w[-1] and '\x1b[?1000;1006l' in w[-1] and v.tty.restored
    class Boom(BaseException): pass
    v = Viewer(p, Tty(Boom()))
    with pytest.raises(Boom): v.run()
    assert '\x1b[?1049l' in v.tty.writes[-1] and v.tty.restored


def test_sub_agent_calls_spend_neither_the_root_budget_nor_its_hooks():
    for writes in (False, True):
        a, _ = fake_agent(max_tool_calls=20)
        a.subagent_writes, hooked = writes, []
        a.registry.on('before_tool', lambda agent, name, args: hooked.append(current_run().kind))
        be = _delegating(a, [], ('delegate_search', {'questions': ['what does a.py define?', 'who imports it?', 'is it tested?']}),
                         reads=8, after=[Step(tool=READ)])
        list(a.stream('go'))
        results = [m['content'] for m in be.hist_ if m['role'] == 'tool']
        assert 'def a' in results[-1], f'24 sub-agent reads refused the root its last read (writes={writes})'
        assert set(hooked) == ({'root', 'child'} if writes else {'root'}), 'read-only sub-agent calls are for display only'


def test_a_resumed_turn_replays_only_the_root_calls():
    from ramabana.agent import _resumed_acts
    a, _ = fake_agent()
    _delegating(a, [])
    list(a.stream('go'))
    out = _resumed_acts(a.history[-1]['activity'])
    assert out.count('view_file(') == 1 and 'delegate_search(' in out


V2 = {'at', 'busy', 'root', 'plan', 'subs', 'files', 'background'}


def test_a_v2_snapshot_has_the_plan_the_files_and_every_sub_agent_call():
    a, _ = fake_agent()
    a.plan.set('ship', ['read a.py', 'fix it', 'test it'])
    a.plan.update(a.plan.todos[0].id, status='done'); a.plan.update(a.plan.todos[1].id, status='active')
    _delegating(a, [], reads=10)
    list(a.stream('go'))
    a.before.update({'/proj/a.py': 'def a(): pass\n', '/proj/big.py': ''})
    a.host.files.update({'/proj/a.py': 'def a(): return 1\n', '/proj/big.py': ''.join(f'x{i} = {i}\n' for i in range(200))})
    snap = now_snapshot(a)
    assert set(snap) == V2 and {'status', 'current', 'steps', 'state', 'turn_elapsed'} <= set(snap['root'])
    assert snap['plan'] == [{'text': 'read a.py', 'status': 'done'}, {'text': 'fix it', 'status': 'active'}, {'text': 'test it', 'status': 'pending'}]
    sub, = snap['subs']
    assert {'id', 'question', 'elapsed', 'state', 'steps', 'status', 'current', 'calls', 'answer'} <= set(sub)
    assert sub['steps'] == 10 and len(sub['calls']) == 8, 'the last eight calls, not all of them'
    call = sub['calls'][-1]
    assert set(call) == {'line', 'ok', 'done', 'out'} and call['ok'] and call['done'] and 'def a' in call['out']
    assert sub['answer'].startswith('a() is defined'), 'a finished sub-agent shows its answer'
    files = {f['path']: f for f in snap['files']}
    assert (files['a.py']['added'], files['a.py']['removed']) == (1, 1) and '+def a(): return 1' in files['a.py']['diff']
    big = files['big.py']
    assert big['added'] == 200 and len(big['diff'].splitlines()) <= 81, 'a long diff is clipped'
    assert json.loads(json.dumps(snap)) == snap


def test_a_long_tool_result_and_answer_are_clipped():
    a, _ = fake_agent()
    a.host.files['/proj/a.py'] = 'y = 1\n' * 400
    class Root(ScriptedBackend):
        def spawn(self, sp='', tools=(), **kw):
            return ScriptedBackend(self.spec, steps=[Step(tool=READ), Step('word ' * 400)], token_delay=0, tools=tools)
    be = Root(steps=[Step(tool=ASK), Step('done')], token_delay=0, tools=a.tools)
    a._be = a._be_or_none = lambda job='turn': be
    list(a.stream('go'))
    sub, = now_snapshot(a)['subs']
    assert len(sub['calls'][0]['out']) < 300 and len(sub['answer']) < 700


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
        return 'running', ''
    monkeypatch.setattr(a.host, 'cmd_output', out, raising=False)
    w = FolderWatch('/proj', 'review it'); a.monitors.watches[w.id] = w
    bg = now_snapshot(a)['background']
    assert all(set(r) == {'kind', 'id', 'label', 'state', 'elapsed'} for r in bg)
    kinds = {r['kind']: r for r in bg}
    assert set(kinds) == {'delegate', 'shell', 'watch'}, 'a shell the host no longer knows is left out'
    assert kinds['delegate']['state'] == 'completed' and kinds['delegate']['label'].startswith('what does a.py')
    assert (kinds['shell']['id'], kinds['shell']['label'], kinds['shell']['state']) == ('cmd_1234abcd', 'pytest -x tests', 'running')
    assert kinds['watch']['id'] == w.id and '/proj' in kinds['watch']['label']
    assert now_snapshot(a)['subs'][0]['id'] == kinds['delegate']['id'], 'a background delegation is a sub-agent too'
    json.dumps(bg)


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


def test_a_steady_snapshot_reads_no_file_and_asks_no_shell(monkeypatch):
    import ramabana.pane as pane
    a, _ = fake_agent()
    a.before['/proj/a.py'] = 'def a(): pass\n'; a.host.files['/proj/a.py'] = 'def a(): return 1\n'
    act = a.activity.start('run_shell_bg', {'command': 'pytest'})
    a.activity.finish(act, "started cmd_aaaaaaaa; read it with shell_output('cmd_aaaaaaaa')")
    done = a.activity.start('run_shell_bg', {'command': 'ls'})
    a.activity.finish(done, "started cmd_bbbbbbbb; read it with shell_output('cmd_bbbbbbbb')")
    reads, asks = [], []
    real = a.host.text_at
    monkeypatch.setattr(a.host, 'text_at', lambda p: (reads.append(p), real(p))[1])
    monkeypatch.setattr(a.host, 'cmd_output', lambda rid, tail=200: (asks.append(rid), ('running' if rid == 'cmd_aaaaaaaa' else 'exit 0', ''))[1], raising=False)
    first = now_snapshot(a)
    assert first['files'][0]['added'] == 1 and sorted(asks) == ['cmd_aaaaaaaa', 'cmd_bbbbbbbb']
    reads.clear(); asks.clear()
    assert now_snapshot(a)['files'] == first['files']
    assert reads == [] and asks == [], 'nothing changed, so nothing is read or asked'
    monkeypatch.setattr(pane, 'SHELL_EVERY', 0)
    now_snapshot(a)
    assert asks == ['cmd_aaaaaaaa'], 'a shell known to have exited is never asked again'
    reads.clear()
    a.host.files['/proj/a.py'] = 'def a(): return 2\n'
    fin = a.activity.start('replace_text', {'path': '/proj/a.py'}); a.activity.finish(fin, 'ok')
    assert '+def a(): return 2' in now_snapshot(a)['files'][0]['diff'] and reads, 'a finished call recomputes the files'


def test_a_quit_leaves_a_mark_beside_the_snapshot_and_a_crash_does_not(tmp_path):
    (p := tmp_path/'now.json').write_text(json.dumps(_board(time.time())))
    for stop in ('q', '\x03', KeyboardInterrupt()):
        quit_mark(p).unlink(missing_ok=True)
        Viewer(p, Tty(stop)).run()
        assert quit_mark(p) == tmp_path/'now.closed' and quit_mark(p).exists(), f'{stop!r} is a quit'
    quit_mark(p).unlink()
    class Boom(BaseException): pass
    with pytest.raises(Boom): Viewer(p, Tty(Boom())).run()
    assert not quit_mark(p).exists(), 'a crash is not a quit'
