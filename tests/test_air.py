"A model that calls tool after tool without a word is reminded once to tell the user where it is, from aai-coding's air hook."
from ramabana.runtime import AIR_CALLS, Run
from ramabana.tools import _inboxed

SAID = 'The cache key ignores the locale, so two tests share one entry and race on it. I am adding the locale to the key next.'
AIR = 'have gone by'   # the air reminder's own words; other reminders, such as a repeated result's, can share its tag


def test_a_silent_stretch_gets_one_nudge_quoting_the_request_and_speaking_resets_it():
    run = Run('r1', question='fix the flaky cache test')
    tool = _inboxed(lambda: 'ok', run)
    outs = [tool() for _ in range(AIR_CALLS)]
    assert all(AIR not in o for o in outs[:-1]), 'nudged too early'
    assert AIR in outs[-1] and 'fix the flaky cache test' in outs[-1]
    assert AIR not in tool(), 'one nudge, then the count starts again'
    for _ in range(AIR_CALLS - 2): tool()
    run.hear(SAID)
    assert all(AIR not in tool() for _ in range(AIR_CALLS - 1)), 'saying something resets the count'


def test_a_sub_agent_is_never_nudged_and_a_user_message_restarts_the_count():
    "A sub-agent reports to its caller, not the user; and a turn just steered answers the steering, not the old request."
    for kind in ('child', 'background', 'monitor'):
        child = _inboxed(lambda: 'ok', Run('c', kind, question='look'))
        assert all(AIR not in child() for _ in range(AIR_CALLS * 2)), kind
    run = Run('r2', question='the old request')
    tool = _inboxed(lambda: 'ok', run)
    for _ in range(AIR_CALLS - 1): tool()
    run.tell('stop that and do this instead')
    out = tool()
    assert 'do this instead' in out and AIR not in out, out
    assert all(AIR not in tool() for _ in range(AIR_CALLS - 1)), 'the steering restarted the count'
