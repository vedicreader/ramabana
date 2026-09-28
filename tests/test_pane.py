"The `now` pane: what a turn and its sub-agents are doing, as a file, and that file drawn."

import json, time
from rich.console import Console

from ramabana.pane import now_snapshot, read_snapshot, render, write_snapshot
from ramabana.runtime import current_run
from ramabana.testing import ScriptedBackend, Step, fake_agent

READ = ('view_file', {'path': '/proj/a.py'})
ASK = ('delegate_search', {'questions': ['what does a.py define?']})


def _delegating(a, seen, ask=ASK):
    "A turn backend whose sub-agents read a file, snapshotting the agent while that read is still running."
    def peek(agent, name, out):
        if (r := current_run()) is not None and r.kind != 'root': seen.append(now_snapshot(a))
    a.registry.on('after_tool', peek)
    class Root(ScriptedBackend):
        def spawn(self, sp='', tools=(), **kw):
            return ScriptedBackend(self.spec, steps=[Step(tool=READ), Step('a() is defined')], token_delay=0, tools=tools)
    be = Root(steps=[Step(tool=READ), Step(tool=ask), Step('done')], token_delay=0, tools=a.tools, sp=a.system_prompt())
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
    mid, = seen
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
