"""`/goal`: an objective a cheap classify call checks after every turn, to decide whether to
auto-continue, stop because it is done, or give up after too many stuck readings in a row.
"""
from ramabana.testing import fake_agent


def test_goal_continues_through_stuck_readings_but_blocks_after_three_running():
    a, _ = fake_agent()
    verdicts = iter(['stuck', 'stuck', 'continue', 'stuck', 'stuck', 'stuck'])
    a.classify = lambda text, labels: next(verdicts)

    assert a.command('/goal') == 'no active goal'
    a.command('/goal fix the flaky test')
    assert a.goal == {'text': 'fix the flaky test', 'stuck': 0, 'steps': 0}
    assert 'fix the flaky test' in a.command('/goal')

    assert a.goal_after_turn('reply 1') == 'Continue toward the goal: fix the flaky test'
    assert a.goal['stuck'] == 1 and a.goal['steps'] == 1
    a.goal_after_turn('reply 2')
    assert a.goal['stuck'] == 2
    a.goal_after_turn('reply 3')                 # a 'continue' verdict resets the streak
    assert a.goal['stuck'] == 0 and a.goal['steps'] == 3

    a.goal_after_turn('reply 4')
    a.goal_after_turn('reply 5')
    assert a.goal_after_turn('reply 6') is None   # three 'stuck' verdicts running blocks it
    assert a.goal is None


def test_a_done_verdict_clears_the_goal_and_no_goal_never_classifies():
    a, _ = fake_agent()
    a.classify = lambda text, labels: (_ for _ in ()).throw(AssertionError('classified with no goal set'))
    assert a.goal_after_turn('anything') is None    # short-circuits before calling classify

    a.classify = lambda text, labels: 'done'
    a.command('/goal ship the feature')
    assert a.goal_after_turn('all fixed') is None
    assert a.goal is None
    assert a.command('/goal clear') == 'no active goal'
    assert 'goal' in a.commands()
