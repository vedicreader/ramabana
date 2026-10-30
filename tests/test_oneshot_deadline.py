"`Agent.oneshot(deadline=...)` bounds routing, preparation and the provider call together, and never pretends a backend can hold a deadline it cannot."
import time

import pytest

from ramabana.core import ModelSpec
from ramabana.runtime import DeadlineUnsupported, OneshotTimeout, RishiBackend, use_chat
from ramabana.testing import FakeBackend, fake_agent

FIRST = ModelSpec('first', 'claude', 'claude-sonnet-5', 200_000)
SECOND = ModelSpec('second', 'claude', 'claude-opus-5', 200_000)
HOSTED = ModelSpec('gpt', 'remote', 'openai/gpt-5.4', 272_000)


class Late(TimeoutError):
    "What rishi's `ClaudeDeadline` looks like: how long the call ran, and whether its stream closed."
    def __init__(self, elapsed, stopped):
        super().__init__('late')
        self.elapsed, self.stopped = elapsed, stopped

class Holder(FakeBackend):
    "A backend that holds a deadline. It records each deadline it was handed, then answers or raises `outcome`."
    supports_deadline = True
    def __init__(self, spec, outcome='answer', **kw):
        super().__init__(spec, **kw)
        self.outcome, self.asked = outcome, []
    def _oneshot(self, prompt, sp, max_tokens, deadline=None):
        self.asked.append(deadline)
        if isinstance(self.outcome, Exception): raise self.outcome
        return self.outcome

class Plain(FakeBackend):
    "A backend with no deadline that counts the one-shots it was asked."
    asked = 0
    def _oneshot(self, prompt, sp, max_tokens):
        self.asked += 1
        return 'answer'

def routed(*backends):
    a, _ = fake_agent()
    routes = iter(backends)
    a._be_or_none = lambda job: next(routes, None)
    return a

def slow(prompt, sp, backend):
    time.sleep(.2)
    return prompt, sp


def test_a_deadline_the_route_cannot_hold_fails_before_the_provider_is_asked():
    plain = Plain(FIRST)
    a = routed(plain, plain, plain)
    with pytest.raises(DeadlineUnsupported, match='first'): a.oneshot('q', deadline=5)
    for bad in (0, -1, True, float('nan'), 'soon'):
        with pytest.raises(ValueError, match='deadline'): a.oneshot('q', deadline=bad)
    assert plain.asked == 0 and not a.routing.down, 'the provider was asked, or the route was set aside'
    assert a.oneshot('q') == 'answer' and plain.asked == 1


def test_the_deadline_covers_preparation_and_hands_each_route_what_is_left():
    held = Holder(FIRST)
    assert routed(held).oneshot('q', prepare=slow, deadline=5) == 'answer'
    assert 3 < held.asked[0] < 4.9, held.asked
    late = Holder(FIRST)
    with pytest.raises(OneshotTimeout) as got: routed(late).oneshot('q', prepare=slow, deadline=.1)
    assert (got.value.route, got.value.stopped) == ('first', True) and got.value.elapsed >= .2 and late.asked == [], 'the provider was asked past the deadline'


class SlowFit(Holder):
    "A backend that takes `lag` seconds to fit a prompt."
    lag = .2
    def count_tokens(self, text):
        time.sleep(self.lag)
        return super().count_tokens(text)

def test_the_deadline_covers_routing():
    held = Holder(FIRST)
    a, _ = fake_agent()
    a._be_or_none = lambda job: time.sleep(.2) or held
    with pytest.raises(OneshotTimeout): a.oneshot('q', deadline=.1)
    assert held.asked == [], 'the provider was asked after routing used the time'


def test_the_deadline_covers_fitting_the_prompt_and_a_later_unsupported_route():
    slow_fit = SlowFit(FIRST)
    with pytest.raises(OneshotTimeout) as got: routed(slow_fit).oneshot('q', deadline=.1)
    assert got.value.route == 'first' and got.value.stopped is True and slow_fit.asked == [], 'the provider was asked after fitting used the time'
    with pytest.raises(OneshotTimeout) as direct: SlowFit(FIRST).oneshot('q', deadline=.1)
    assert direct.value.elapsed >= .2, 'the backend reported the deadline as the time spent'
    empty, plain = Holder(FIRST, ''), Plain(SECOND)
    with pytest.raises(DeadlineUnsupported, match='second'): routed(empty, plain).oneshot('q', deadline=5)
    assert len(empty.asked) == 1 and plain.asked == 0, 'a route the deadline cannot cover was asked'


def test_a_timeout_is_typed_and_never_falls_back_to_another_route():
    for stopped in (False, True):
        first, second = Holder(FIRST, Late(1.5, stopped)), Holder(SECOND)
        a = routed(first, second)
        with pytest.raises(OneshotTimeout) as got: a.oneshot('q', deadline=2)
        t = got.value
        assert (t.route, t.stopped) == ('first', stopped) and 0 <= t.elapsed < 2 and isinstance(t.__cause__, Late), t
        assert second.asked == [] and not a.routing.down, 'a timeout fell back to the next route'
        assert first.problems == [] and 'failed' not in first.note, 'a timeout was recorded as a failure'


def test_a_timeout_a_backend_raised_reaches_the_caller_as_the_same_object():
    first = Holder(FIRST, OneshotTimeout('first', 3.2, True))
    a = routed(first, Holder(SECOND))
    with pytest.raises(OneshotTimeout) as got: a.oneshot('q', deadline=5)
    assert got.value is first.outcome and got.value.elapsed == 3.2, 'the timeout was rebuilt with the time since the agent began'
    assert first.problems == [] and not a.routing.down


class Named:
    "A rishi chat stand-in that holds a `deadline`, and runs out of time below one second."
    oneshot_deadline_ok = True
    def __init__(self, model_id, **kw): self.kw, self.hist, self.asked = kw, [], []
    def oneshot(self, prompt, sp='', think=None, max_tokens=None, deadline=None):
        self.asked.append(deadline)
        if deadline is not None and deadline < 1: raise Late(deadline, True)
        return 'answer'

class Recorded(Named):
    "A recorded chat takes `**kw` and leaves the capability flag False."
    oneshot_deadline_ok = False
    def oneshot(self, prompt, sp='', **kw):
        self.asked.append(kw)
        return 'answer'

class Unflagged(Named):
    "A chat whose `oneshot` names a `deadline` but that does not claim to hold it."
    oneshot_deadline_ok = False

def test_a_claude_backend_holds_a_deadline_only_when_its_chat_says_so():
    be = RishiBackend(FIRST)
    with use_chat(Named):
        assert be.oneshot('q', deadline=5, if_busy=None) == 'answer' and 4 < be.chat.asked[0] <= 5
        with pytest.raises(Late): be.oneshot('q', deadline=.5)
    hosted = RishiBackend(HOSTED)
    with use_chat(Named): assert hosted.oneshot('q', deadline=5) == 'answer' and hosted.chat.asked, 'the chat flag alone decides'
    for spec, chat in ((FIRST, Recorded), (FIRST, Unflagged)):
        be = RishiBackend(spec)
        with use_chat(chat):
            with pytest.raises(DeadlineUnsupported): be.oneshot('q', deadline=5)
            assert be.chat.asked == [], f'{spec.name} was asked'
            assert be.oneshot('q') == 'answer'


@pytest.mark.skipif(not hasattr(pytest.importorskip('rishi.claude'), 'ClaudeDeadline'), reason='the installed rishi predates ClaudeDeadline')
def test_rishis_claude_deadline_becomes_a_oneshot_timeout():
    from rishi.claude import ClaudeChat, ClaudeDeadline
    assert ClaudeChat.oneshot_deadline_ok is True, 'supports_deadline would read False for the real chat'
    a = routed(Holder(FIRST, ClaudeDeadline(1.5, False)))
    with pytest.raises(OneshotTimeout) as got: a.oneshot('q', deadline=2)
    assert got.value.stopped is False and isinstance(got.value.__cause__, ClaudeDeadline)