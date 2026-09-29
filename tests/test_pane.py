"The `now` pane: what a turn and its sub-agents are doing, as a file, and that file drawn."

import json, time
from rich.console import Console

from ramabana.pane import now_snapshot, read_snapshot, render, write_snapshot
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


def _text(snap, width=40, now=None):
    con = Console(record=True, width=width, color_system=None)
    con.print(render(snap, width, now=now))
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


def _sub(id, state, secs, current='', q='which files import fastllm and why?'):
    return {'id': id, 'question': q, 'elapsed': secs, 'current': current, 'state': state, 'steps': 3}


def test_render_draws_idle_busy_and_finished_sub_agents():
    now = time.time()
    assert 'waiting' in _text(None)
    idle = {'at': now, 'busy': False, 'root': {'turn_elapsed': 9, 'steps': 4, 'current': '', 'state': 'completed'}, 'subs': []}
    assert 'idle' in _text(idle, now=now)
    busy = {'at': now - 5, 'busy': True,
            'root': {'turn_elapsed': 12, 'steps': 3, 'current': 'Delegate 2 questions', 'state': 'running'},
            'subs': [_sub('run_aaa', 'running', 4, 'Search code: fastllm'), _sub('run_bbb', 'completed', 2),
                     _sub('run_ccc', 'failed', 1)]}
    out = _text(busy, now=now)
    assert 'main' in out and 'step 3' in out and '17s' in out, 'a running clock advances past the write'
    assert 'Delegate 2 questions' in out and 'Search code: fastllm' in out
    assert '▶ run_aaa' in out and '✓ run_bbb' in out and '✗ run_ccc' in out
    assert all(len(l) <= 40 for l in out.splitlines()), 'long lines are cut, not wrapped'


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
