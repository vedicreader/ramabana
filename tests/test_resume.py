"""Resuming a saved conversation: what of it reaches the model's context.

A resume rebuilds context from the durable turn log, which is the only record that survives the
process. Nothing here loads a model.
"""
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
