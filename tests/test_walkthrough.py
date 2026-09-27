"""`/walkthrough`: this turn's `changes()` as a narrative, cached by diff hash so an unchanged
turn does not re-spend the summary job.
"""
from ramabana.testing import fake_agent


def test_walkthrough_summarises_the_diff_once_and_reuses_it_for_the_same_change():
    a, _ = fake_agent()
    calls = []
    a.summarise = lambda text, sp='': (calls.append(text), 'stop 1: [key change] did the thing')[1]

    assert a.walkthrough() == 'nothing changed this turn'
    assert calls == []

    a.before['/proj/a.py'] = 'x = 1\n'
    a.host.write('/proj/a.py', 'x = 2\n')
    out = a.walkthrough()
    assert out == 'stop 1: [key change] did the thing'
    assert len(calls) == 1 and 'x = 1' in calls[0] and 'x = 2' in calls[0]

    assert a.walkthrough() == out
    assert len(calls) == 1, 'the same diff must not re-spend the summary job'

    a.before['/proj/a.py'] = 'x = 2\n'
    a.host.write('/proj/a.py', 'x = 3\n')
    a.walkthrough()
    assert len(calls) == 2, 'a different diff gets its own summary'
    assert 'walkthrough' in a.commands()
    assert a.command('/walkthrough') == 'stop 1: [key change] did the thing'
