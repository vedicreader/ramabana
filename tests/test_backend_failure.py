"A model failure the backend caught is recorded as a failed turn, not a finished one."
from ramabana.testing import fake_agent


class ClaudeError(Exception): pass


def _failing(be):
    def boom(msg, **kw): raise ClaudeError("claude failed: The model's tool call could not be parsed")
    be._send = boom
    return be


def test_a_caught_model_failure_is_a_failed_turn():
    agent, be = fake_agent()
    _failing(be)
    reply = agent.ask('which files are big?')
    row = agent.history[-1]
    assert 'could not be parsed' in reply and row['reply'] == reply
    assert row['state'] == 'failed' and 'ClaudeError' in row['error'], row


def test_a_caught_failure_while_streaming_is_a_failed_turn():
    agent, be = fake_agent()
    _failing(be)
    text = ''.join(agent.stream('which files are big?'))
    row = agent.history[-1]
    assert 'could not be parsed' in text
    assert row['state'] == 'failed' and 'ClaudeError' in row['error'], row


def test_the_next_turn_after_a_failure_is_complete():
    agent, be = fake_agent(replies=['fine'])
    _failing(be)
    agent.ask('first')
    del be._send   # the class's scripted reply again
    assert agent.ask('second') == 'fine'
    assert agent.history[-1]['state'] == 'complete' and agent.history[-1]['error'] == ''
