"The `now` pane: what a turn and its sub-agents are doing, as a file, and that file drawn."

import json, time
from rich.console import Console

from ramabana.pane import now_snapshot, render
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
        be = _delegating(a, [], ('delegate_search', {'questions': ['what does a.py define?', 'who imports it?', 'is it tested?']}),
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
    assert all(set(r) == {'kind', 'id', 'label', 'state', 'elapsed', 'detail'} for r in bg)
    kinds = {r['kind']: r for r in bg}
    assert set(kinds) == {'delegate', 'shell', 'watch'}, 'a shell the host no longer knows is left out'
    assert kinds['delegate']['state'] == 'completed' and kinds['delegate']['label'].startswith('what does a.py')
    assert (kinds['shell']['id'], kinds['shell']['label'], kinds['shell']['state']) == ('cmd_1234abcd', 'pytest -x tests', 'running')
    assert kinds['watch']['id'] == w.id and '/proj' in kinds['watch']['label']
    assert kinds['shell']['detail'].endswith('3 passed') and 'all files · 0 reviews' == kinds['watch']['detail'], 'a row opens to what it has to show'
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


def test_notes_fold_to_a_line_each_and_the_newest_starts_open():
    now = time.time()
    old, new = {'at': now - 60, 'text': 'Reading the loader first, because it decides which model takes the turn.'}, \
               {'at': now, 'text': 'The loader picks the model from the routing table, so the tests go next.'}
    snap = {**_board(now), 'notes': [old, new]}
    def notes(open=()):
        rows = _text(snap, width=40, now=now, open=open).splitlines()
        return rows[rows.index('Notes') + 1:]
    shut = notes()
    assert '▾' in shut[0] and 'routing' in ' '.join(shut[:4]), 'the newest is open, wrapped to the pane'
    assert sum('▸' in r for r in shut) == 1 and 'decides which model' not in ' '.join(shut), 'an older note is one clipped line'
    assert max(len(r) for r in shut) <= 40
    both = notes(open={('note', old['at'])})
    assert 'decides which model' in ' '.join(both) and '▸' not in ' '.join(both), 'opening an older note shows all of it'
    assert '▾' not in ' '.join(notes(open={('note', new['at'])})), 'and the newest closes like any other row'
    assert 'Notes' not in _text(_board(now), now=now), 'a snapshot without notes draws no section'


def test_a_background_row_opens_to_its_output_review_or_sub_agent():
    now = time.time()
    snap = _board(now)
    snap['background'] = [{'kind': 'shell', 'id': 'cmd_1234abcd', 'label': 'pytest -x tests', 'state': 'running', 'elapsed': 30, 'detail': 'collected 12 items\n3 passed'},
                          {'kind': 'watch', 'id': 'w_1', 'label': '/proj', 'state': 'ok', 'elapsed': None, 'detail': 'all files · 1 review\nlooks fine'},
                          {'kind': 'delegate', 'id': 'run_bbb', 'label': 'is the pane tested?', 'state': 'completed', 'elapsed': 8, 'detail': ''}]
    shut = _text(snap, width=60, now=now)
    assert '3 passed' not in shut and 'looks fine' not in shut and '▸ ✓ delegate' in shut, 'rows start shut'
    opened = _text(snap, width=60, now=now, open={('bg', 'cmd_1234abcd'), ('bg', 'w_1'), ('bg', 'run_bbb')})
    assert '3 passed' in opened and 'looks fine' in opened
    assert opened.count('Yes: tests/test_pane.py covers render') == 1, 'a delegation opens to its sub-agent detail; its sub-agent row stays shut'
