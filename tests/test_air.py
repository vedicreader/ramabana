"A model that calls tool after tool without a word is reminded once to tell the user where it is, from aai-coding's air hook."
from ramabana.runtime import AIR_CALLS, Run
from ramabana.tools import _inboxed

SAID = 'The cache key ignores the locale, so two tests share one entry and race on it. I am adding the locale to the key next.'


def test_a_silent_stretch_gets_one_nudge_quoting_the_request_and_speaking_resets_it():
    run = Run('r1', question='fix the flaky cache test')
    tool = _inboxed(lambda: 'ok', run)
    outs = [tool() for _ in range(AIR_CALLS)]
    assert all('system-reminder' not in o for o in outs[:-1]), 'nudged too early'
    assert 'system-reminder' in outs[-1] and 'fix the flaky cache test' in outs[-1]
    assert 'system-reminder' not in tool(), 'one nudge, then the count starts again'
    for _ in range(AIR_CALLS - 2): tool()
    run.hear(SAID)
    assert all('system-reminder' not in tool() for _ in range(AIR_CALLS - 1)), 'saying something resets the count'
