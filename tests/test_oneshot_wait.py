"""`Agent.oneshot(wait=, strict=)` and `oneshot_stream(fallback=)`: an app that shares one agent among threads
waits for a busy backend, is told why no route answered, and gets a whole reply from a route that cannot stream.

abhyasa held its own lock for each backend, copied ramabana's notes into its own errors, and caught `StreamUnsupported` itself.
"""
import threading, time

import pytest

from ramabana.runtime import OneshotEmpty, OneshotTimeout, StreamUnsupported
from ramabana.core import ModelSpec
from ramabana.testing import FakeBackend, fake_agent

CLOUD = ModelSpec('cloud', 'remote', 'openai/gpt-5.4', 272_000)


class Slow(FakeBackend):
    "A backend whose one-shot waits until `go` is set."
    supports_deadline = True
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.go, self.inside = threading.Event(), threading.Event()
    def _oneshot(self, prompt, sp, max_tokens, deadline=None):
        self.inside.set(); self.go.wait(5)
        return f'answer to {prompt}'


def busy_agent():
    a, _ = fake_agent()
    b = Slow()
    a._be = a._be_or_none = lambda job='turn': b
    first = []
    t = threading.Thread(target=lambda: first.append(a.oneshot('one')))
    t.start(); b.inside.wait(5)
    return a, b, t, first


def test_without_wait_a_busy_backend_answers_nothing():
    a, b, t, first = busy_agent()
    assert a.oneshot('two') == ''
    b.go.set(); t.join(5)
    assert first == ['answer to one']


def test_with_wait_both_threads_get_an_answer():
    a, b, t, first = busy_agent()
    got = []
    t2 = threading.Thread(target=lambda: got.append(a.oneshot('two', wait=True)))
    t2.start(); time.sleep(.1)
    assert not got, 'the second call waits for the first'
    b.go.set(); t.join(5); t2.join(5)
    assert first == ['answer to one'] and got == ['answer to two']


def test_a_wait_past_the_deadline_raises():
    a, b, t, _ = busy_agent()
    with pytest.raises(OneshotTimeout): a.oneshot('two', wait=True, deadline=.2)
    b.go.set(); t.join(5)


class Mute(FakeBackend):
    "A cloud backend that answers nothing."
    def _oneshot(self, prompt, sp, max_tokens): return ''


def test_strict_says_why_no_route_answered():
    a, _ = fake_agent()
    b = Mute(CLOUD)
    a._be = lambda job='turn': b
    a._be_or_none = lambda job='turn': None if b.spec.name in a.routing.down else b
    assert a.oneshot('q') == '', 'not strict: an empty answer, as before'
    a.routing.down.clear()
    with pytest.raises(OneshotEmpty) as e: a.oneshot('q', job='summary', strict=True)
    assert e.value.job == 'summary' and b.spec.name in e.value.why and 'answered nothing' in e.value.why


def test_strict_passes_an_answer_through():
    a, _ = fake_agent()
    assert a.oneshot('q', strict=True).startswith('ONESHOT:')


def test_fallback_gives_a_route_that_cannot_stream_as_one_chunk():
    a, _ = fake_agent()   # FakeBackend cannot stream
    with pytest.raises(StreamUnsupported): list(a.oneshot_stream('q'))
    assert list(a.oneshot_stream('q', fallback=True)) == ['ONESHOT:q']


def test_strict_stream_with_no_text_raises():
    a, _ = fake_agent()
    b = Mute(CLOUD)
    a._be = lambda job='turn': b
    a._be_or_none = lambda job='turn': None if b.spec.name in a.routing.down else b
    with pytest.raises(OneshotEmpty): list(a.oneshot_stream('q', fallback=True, strict=True))
