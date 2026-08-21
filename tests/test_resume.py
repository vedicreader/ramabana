"""Resuming a saved conversation: what of it reaches the model's context.

A resume rebuilds context from the durable turn log, which is the only record that survives the
process. Nothing here loads a model.
"""
import json
import threading
import pytest
from ramabana.agent import RESUME_DETAIL, _resumed_acts
from ramabana.testing import fake_agent

MODEL = 'gpt-mini'   # a registered name: `resume_session` puts the session's model back


def _turn(session, prompt, reply, activity=(), model=MODEL):
    return {'at': 0, 'session': session, 'prompt': prompt, 'reply': reply,
            'model': model, 'activity': list(activity)}


def _act(tool, args=None, detail='', ok=True):
    return {'tool': tool, 'args': dict(args or {}), 'detail': detail, 'ok': ok}


# -- the rendering ---------------------------------------------------------------------

def test_nothing_renders_as_nothing():
    "No acts, and rows that are not acts, add no assistant text at all."
    assert _resumed_acts(None) == ''
    assert _resumed_acts([]) == ''
    assert _resumed_acts([{'no': 'tool'}, 'junk', None]) == ''


def test_a_call_carries_its_tool_args_and_result():
    out = _resumed_acts([_act('view_file', {'path': 'a.py'}, detail='def a(): pass')])
    assert '- view_file(path=a.py)' in out
    assert 'def a(): pass' in out
    assert 'truncated' in out          # the model is told the record is lossy


def test_a_failed_call_says_so():
    "A resumed context that hides failures invites the model to repeat them."
    out = _resumed_acts([_act('run_shell', {'cmd': 'ls /nope'}, detail='not found', ok=False)])
    assert '[failed]' in out and 'not found' in out


def test_a_long_result_is_clipped_and_declares_it():
    out = _resumed_acts([_act('grep', {'q': 'x'}, detail='y' * (RESUME_DETAIL + 500))])
    assert 'more chars]' in out
    assert out.count('y') <= RESUME_DETAIL + 10


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


def test_a_turn_that_only_worked_is_not_dropped(tmp_path):
    "An interrupted turn has tool calls and no reply; its work is still context."
    a, be = fake_agent(cfg=tmp_path)
    a.history = [_turn('s1', 'go', '', [_act('run_shell', {'cmd': 'ls'}, detail='a.py')])]

    a.resume_session('s1')

    assert [m['role'] for m in be._resume_hist] == ['user', 'assistant']
    assert 'run_shell(cmd=ls)' in be._resume_hist[1]['content']


def test_a_turn_with_neither_reply_nor_calls_adds_no_assistant_message(tmp_path):
    a, be = fake_agent(cfg=tmp_path)
    a.history = [_turn('s1', 'go', '')]

    a.resume_session('s1')

    assert [m['role'] for m in be._resume_hist] == ['user']


def test_resume_only_takes_the_session_it_was_asked_for(tmp_path):
    a, be = fake_agent(cfg=tmp_path)
    a.history = [_turn('s1', 'first', 'one'), _turn('s2', 'second', 'two')]

    a.resume_session('s2')

    assert [m['content'] for m in be._resume_hist] == ['second', 'two']


def test_session_metadata_persists_and_refreshes_between_agents(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    a.history = [_turn('s1', 'first prompt', 'reply')]
    a.set_title('Manual title')
    a.set_muted(True)

    b, _ = fake_agent(cfg=tmp_path)
    b.history = list(a.history)
    assert b.session_meta('s1')['title'] == 'Manual title'
    assert b.session_meta('s1')['muted'] is True
    assert b.sessions()[0]['title'] == 'Manual title'

    a.history_path.write_text(json.dumps(_turn('s2', 'new elsewhere', 'reply')) + '\n')
    b.refresh_history()
    assert [s['id'] for s in b.sessions()] == ['s2']


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


def test_malformed_session_metadata_is_reported_and_not_replaced(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    a.sessions_path.write_text('{broken')
    before = a.sessions_path.read_text()
    assert a.session_meta()['title'] == '' and 'malformed' in a.history_problem
    with pytest.raises(ValueError, match='malformed'): a.set_title('No overwrite')
    assert a.sessions_path.read_text() == before


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


def test_a_failed_summary_keeps_the_title_and_does_not_back_off(tmp_path, monkeypatch):
    "Advancing the turn count on failure would spend the retry the doubling rule was saving."
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    a.history = [_turn('s1', 'one', 'reply')]
    def broken(*args): raise RuntimeError('no summary model')
    monkeypatch.setattr(a, 'oneshot', broken)
    meta = a.summarize_session()
    assert meta['title'] == 'one' and meta['title_turns'] == 0
    assert 'title summary failed' in a.history_problem
    monkeypatch.setattr(a, 'oneshot', lambda *args: 'Named at last')
    assert a.summarize_session()['title'] == 'Named at last'


def test_a_turn_write_does_not_call_the_summary_model(tmp_path, monkeypatch):
    "`_remember` is on the turn path; a title is worth a model call but not one held inside a write."
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    monkeypatch.setattr(a, 'oneshot', lambda *args: (_ for _ in ()).throw(AssertionError('summarised in _remember')))
    a._remember('one', 'reply')
    assert a.history and a.history[-1]['prompt'] == 'one'


def test_automatic_titles_follow_doubling_and_never_replace_manual_titles(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    a.session_id = 's1'
    calls = []
    monkeypatch.setattr(a, 'oneshot', lambda *args: calls.append(args) or f'Title {len(calls)}')
    a.history = [_turn('s1', 'one', 'reply')]
    assert a.summarize_session()['title'] == 'Title 1'
    a.history.append(_turn('s1', 'two', 'reply'))
    assert a.summarize_session()['title'] == 'Title 2'
    a.history.append(_turn('s1', 'three', 'reply'))
    assert a.summarize_session()['title'] == 'Title 2' and len(calls) == 2
    a.set_title('Chosen')
    a.history.extend([_turn('s1', 'four', 'reply'), _turn('s1', 'five', 'reply')])
    assert a.summarize_session()['title'] == 'Chosen' and len(calls) == 2


def test_a_resumed_session_is_told_what_it_no_longer_reaches():
    """Roots opened during a session do not come back with it: a resume rebuilds from the log, and
    silently re-widening the write boundary is not something a log should be able to do. What it can
    do is say that the boundary used to be wider, so the person can open it again knowingly.
    """
    a, _ = fake_agent(replies=['ok'])
    a.history = [{'session': 's1', 'activity': [
                    {'tool': 'add_root', 'args': {'path': '/srv/app'}, 'ok': True},
                    {'tool': 'view_file', 'args': {'path': 'a.py'}, 'ok': True}]},
                 {'session': 's1', 'activity': [
                    {'tool': 'add_root', 'args': {'path': '/srv/app'}, 'ok': True},
                    {'tool': 'add_root', 'args': {'path': '~/notes'}, 'ok': True}]},
                 {'session': 's2', 'activity': [
                    {'tool': 'add_root', 'args': {'path': '/elsewhere'}, 'ok': True}]}]
    assert a.session_added_roots('s1') == ['/srv/app', '~/notes']   # deduped, and s2 is not ours
    assert a.session_added_roots('s2') == ['/elsewhere']
    assert a.session_added_roots('nope') == []

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


def test_switching_a_branch_rebuilds_its_context_and_never_copies_another(tmp_path):
    a, _ = fake_agent(replies=['one', 'two'], cfg=tmp_path)
    a.ask('q1'); a.ask('q2')
    turn = list(a.checkpoints)[-1]
    whole = len(a.compile_context(turn, 'after')['messages'])
    undone = a.undo_turn(turn)
    assert a.switch_branch('main')['branch_id'] == 'main' and a.current_branch_id == 'main'
    assert len(a.compile_context(turn, 'after')['messages']) == whole, 'main was left as it was'
    assert a.switch_branch(undone['branch_id'])['branch_id'] == undone['branch_id']
    assert a.switch_branch(undone['branch_id'])['branch_id'] == undone['branch_id'], 'idempotent'


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


def test_keep_beats_discard_when_they_would_split_a_group(tmp_path):
    "An explicit keep is a person's answer to the dependency, so it wins over the other end's discard."
    a, _ = fake_agent(replies=['done'], cfg=tmp_path)
    a.ask('q')
    turn = list(a.checkpoints)[-1]
    a.checkpoints[turn]['after'][:] = [{'role': 'user', 'content': 'q'},
        {'role': 'assistant', 'tool_calls': [{'id': 'c1'}]},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r'}]
    parts = a.context_parts(turn, 'after')
    both = a.compile_context(turn, 'after', manifest={parts[1]['part_id']: 'keep',
                                                      parts[2]['part_id']: 'discard'})
    assert len(both['messages']) == 3 and both['omitted'] == 0


def test_an_unknown_context_policy_is_refused_rather_than_ignored(tmp_path):
    a, _ = fake_agent(replies=['one'], cfg=tmp_path)
    a.ask('q')
    turn = list(a.checkpoints)[-1]
    part = a.context_parts(turn, 'after')[0]['part_id']
    with pytest.raises(ValueError, match='policy'): a.compile_context(turn, 'after', manifest={part: 'maybe'})
    with pytest.raises(ValueError, match='policy'): a.save_branch('b1', manifest={part: 'maybe'})


def test_a_branch_point_that_does_not_exist_is_named_not_guessed(tmp_path):
    a, _ = fake_agent(replies=['one'], cfg=tmp_path)
    a.ask('q')
    turn = list(a.checkpoints)[-1]
    with pytest.raises(ValueError, match='no part'): a.compile_context(turn, 'after', part_id='nope:9')
    with pytest.raises(KeyError): a.compile_context('no-such-turn', 'after')
    with pytest.raises(KeyError): a.switch_branch('branch_never_recorded')

