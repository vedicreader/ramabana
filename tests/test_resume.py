"""Resuming a saved conversation: what of it reaches the model's context.

A resume rebuilds context from the durable turn log, which is the only record that survives the
process. Nothing here loads a model.
"""
import json
import threading
import pytest
from ramabana.testing import fake_agent

MODEL = 'gpt-mini'   # a registered name: `resume_session` puts the session's model back


def _turn(session, prompt, reply, activity=(), model=MODEL):
    return {'at': 0, 'session': session, 'prompt': prompt, 'reply': reply,
            'model': model, 'activity': list(activity)}


def _act(tool, args=None, detail='', ok=True):
    return {'tool': tool, 'args': dict(args or {}), 'detail': detail, 'ok': ok}


# -- the resume ------------------------------------------------------------------------

def test_resume_puts_tool_calls_back_into_context(tmp_path):
    "The whole point: a resumed turn carries what the model did, not only what it said."
    a, be = fake_agent(cfg=tmp_path)
    a.history = [_turn('s1', 'read the file', 'It defines a().',
                       [_act('view_file', {'path': 'a.py'}, detail='def a(): pass')])]

    a.resume_session('s1')

    hist = be._resume_hist
    assert [m['role'] for m in hist] == ['user', 'assistant']
    assert hist[0]['content'] == 'read the file'
    assert 'view_file(path=a.py)' in hist[1]['content']
    assert 'def a(): pass' in hist[1]['content']
    assert hist[1]['content'].endswith('It defines a().')   # the reply stays last
    assert a.session_id == 's1'


def test_a_model_change_before_the_first_turn_keeps_the_resumed_conversation(tmp_path):
    """The backend starts lazily, so a resume waits in `_resume_hist`; `snapshot_hist` read only the
    live chat, and a `set_model` before the first turn carried an empty conversation across."""
    from ramabana import NullHost
    from ramabana.agent import Agent
    a = Agent(NullHost(), model=MODEL, cfg=tmp_path)   # a real routing; no backend starts, so no model loads
    a.history = [_turn('s1', 'read the file', 'It defines a().', model='claude-opus-5-5')]
    a.resume_session('s1')
    assert [m['content'] for m in a._be('turn').snapshot_hist()] == ['read the file', 'It defines a().']
    a.set_model(MODEL)
    assert a.model.name == MODEL
    assert [m['content'] for m in a._be('turn').snapshot_hist()] == ['read the file', 'It defines a().']


def test_concurrent_session_metadata_updates_merge(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    b, _ = fake_agent(cfg=tmp_path)
    a.session_id, b.session_id = 's1', 's2'
    workers = [threading.Thread(target=a.set_title, args=('One',)),
               threading.Thread(target=b.set_title, args=('Two',))]
    for worker in workers: worker.start()
    for worker in workers: worker.join()
    rows = json.loads(a.sessions_path.read_text())['sessions']
    assert rows['s1']['title'] == 'One' and rows['s2']['title'] == 'Two'


def test_a_session_the_sidecar_is_silent_about_keeps_its_derived_title(tmp_path):
    """Merging the sidecar over `sessions()` must add what a person set, not blank what was derived.
    A row written by muting alone carries an empty title, and that is not a title."""
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    a.history = [_turn('s1', 'the derived one', 'reply'), _turn('s2', 'another', 'reply')]
    a.set_muted(True, 's1')
    rows = {row['id']: row for row in a.sessions()}
    assert rows['s1']['title'] and rows['s1']['muted'] is True
    assert rows['s2']['title'] and rows['s2']['muted'] is False
    a.set_title('Chosen', 's1')
    assert {row['id']: row['title'] for row in a.sessions()}['s1'] == 'Chosen'


def test_a_branch_is_its_parent_point_and_its_manifest_and_both_survive_a_reload(tmp_path):
    """A branch is not a copy of a conversation. It is where it came from plus what it keeps, so
    switching to one recompiles it and a reload finds the same thing."""
    from ramabana.core import BranchChanged
    a, _ = fake_agent(replies=['one', 'two'], cfg=tmp_path)
    a.ask('q1'); a.ask('q2')
    turn = list(a.checkpoints)[-1]

    undone = a.undo_turn(turn)
    assert undone['stage'] == 'before' and undone['parent_branch_id'] == 'main'
    assert undone['parent_turn_id'] == turn and undone['revision'] == 1
    assert a.current_branch_id == undone['branch_id']

    a.refresh_history()
    assert a.branch_meta(undone['branch_id'])['parent_turn_id'] == turn, 'read back from the sidecar'
    with pytest.raises(BranchChanged): a.save_branch(undone['branch_id'], revision=0)


def test_a_call_and_its_result_are_one_decision(tmp_path):
    """Half a tool exchange is not a conversation any provider will accept, so a part inside one
    takes the whole group with it and discarding either end discards both."""
    a, _ = fake_agent(replies=['done'], cfg=tmp_path)
    a.ask('q')
    turn = list(a.checkpoints)[-1]
    hist = a.checkpoints[turn]['after']
    hist[:] = [{'role': 'user', 'content': 'q'},
               {'role': 'assistant', 'tool_calls': [{'id': 'c1'}]},
               {'role': 'tool', 'tool_call_id': 'c1', 'content': 'result'},
               {'role': 'assistant', 'content': 'done'}]
    parts = a.context_parts(turn, 'after')
    assert [p['kind'] for p in parts] == ['user', 'calls', 'result', 'assistant']
    assert parts[1]['group'] == parts[2]['group'], 'the call and its result share one group'
    assert parts[0]['group'] != parts[1]['group'] != parts[3]['group']

    cut = a.compile_context(turn, 'after', part_id=parts[1]['part_id'])
    assert [m.get('role') for m in cut['messages']] == ['user', 'assistant', 'tool'], \
        'branching at the call carries its result rather than orphaning it'
    gone = a.compile_context(turn, 'after', manifest={parts[2]['part_id']: 'discard'})
    assert [m.get('role') for m in gone['messages']] == ['user', 'assistant'] and gone['omitted'] == 2
    assert parts[1]['part_id'] in gone['adjusted'], 'and it says which part it took with it'
