"`Agent.oneshot_stream` yields a one-shot reply as the model sends it, hands over to the next route only before the first text, and counts what a one-shot spends against the agent's budgets."
import asyncio, sys, threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ramabana.core import AgentError, ModelSpec
from urai.core import UsageStats

from ramabana.runtime import BudgetExceeded, DeadlineUnsupported, OneshotTimeout, RishiBackend, StreamUnsupported, Usage, use_chat
from ramabana.testing import FakeBackend, fake_agent

FIRST = ModelSpec('first', 'remote', 'openai/gpt-5.4', 272_000)
SECOND = ModelSpec('second', 'remote', 'openai/gpt-5.5', 272_000)


class Late(TimeoutError):
    "What rishi's `ClaudeDeadline` looks like: how long the call ran, and whether its stream closed."
    def __init__(self, elapsed, stopped):
        super().__init__('late')
        self.elapsed, self.stopped = elapsed, stopped


class Streams(FakeBackend):
    "A backend that streams `parts`, then raises `boom`, and reports `spent` for each call it ran."
    supports_stream = supports_deadline = True
    def __init__(self, spec, parts=(), spent=None, boom=None, **kw):
        super().__init__(spec, **kw)
        self.parts, self.spent, self.boom = list(parts), spent, boom
        self.given, self.deadlines, self.closed, self.calls = [], [], 0, 0
    def _oneshot_stream(self, prompt, sp, max_tokens, deadline=None):
        self.calls += 1; self.deadlines.append(deadline)
        try:
            for p in self.parts:
                self.given.append(p)
                yield p
            if self.boom: raise self.boom
        finally: self.closed += 1
    def _oneshot(self, prompt, sp, max_tokens, deadline=None):
        self.calls += 1
        return ''.join(self.parts)
    def _reported(self): return None if self.spent is None else Usage(**self.spent.dict())


class Silent(Streams):
    "A backend with no stream and no deadline, which counts the one-shots it was asked."
    supports_stream = supports_deadline = False
    asked = 0
    def _oneshot(self, prompt, sp, max_tokens):
        self.asked += 1
        return 'whole'


def routed(*backends, **kw):
    "An agent whose job goes to the first of `backends` not set aside."
    a, _ = fake_agent(**kw)
    a._be_or_none = lambda job: next((b for b in backends if b.spec.name not in a.routing.down), None)
    return a


def test_the_first_chunk_arrives_before_the_model_finishes_and_a_closed_stream_is_counted_once():
    be = Streams(FIRST, ['Hel', 'lo', ' there'], spent=Usage(input=20, output=3, total=23, cost=.5))
    a = routed(be)
    it = a.oneshot_stream('question', 'brief')
    assert next(it) == 'Hel' and be.given == ['Hel'], 'the first chunk waited for the whole reply'
    assert be.lock.locked()
    it.close()
    assert be.closed == 1 and not be.lock.locked(), 'closing the iterator left the provider stream or the backend held'
    assert (a.use.total, a.use.cost) == (23, .5)
    assert list(a.oneshot_stream('again')) == ['Hel', 'lo', ' there'] and (a.use.total, a.use.cost) == (46, 1.0), 'the backend was not reusable, or a call was not counted'
    assert a.turn_use.total == 0 and a._usage_seen == {} and a.use.turns == 0


def test_a_route_that_says_nothing_hands_over_but_one_that_has_spoken_never_does():
    quiet, loud = Streams(FIRST), Streams(SECOND, ['b', 'c'])
    a = routed(quiet, loud)
    assert list(a.oneshot_stream('q')) == ['b', 'c'] and 'first' in a.routing.down and quiet.closed == 1
    broken, spare = Streams(FIRST, ['a'], boom=RuntimeError('lost')), Streams(SECOND, ['z'])
    a, got = routed(broken, spare), []
    with pytest.raises(RuntimeError, match='lost'):
        for t in a.oneshot_stream('q'): got.append(t)
    assert got == ['a'] and spare.calls == 0 and broken.closed == 1 and not broken.lock.locked()
    early, spare = Streams(FIRST, boom=RuntimeError('refused')), Streams(SECOND, ['z'])
    assert list(routed(early, spare).oneshot_stream('q')) == ['z'], 'an error before any text was not handed over'

    def refuse(prompt, sp, backend):
        if backend.spec.name == 'second': raise ValueError('outgoing text refused')
        return prompt, sp
    quiet, loud = Streams(FIRST), Streams(SECOND, ['x'])
    with pytest.raises(ValueError, match='refused'): list(routed(quiet, loud).oneshot_stream('q', prepare=refuse))
    assert loud.calls == 0 and quiet.closed == 1 and not quiet.lock.locked() and not loud.lock.locked()


def test_a_busy_backend_ends_the_stream_unmarked_and_an_unsupported_one_is_refused_unasked():
    busy, other = Streams(FIRST, ['a'], spent=Usage(total=5, cost=.1)), Streams(SECOND, ['b'])
    a = routed(busy, other)
    assert list(a.oneshot_stream('q')) == ['a'] and a.use.total == 5
    with busy.lock: assert list(a.oneshot_stream('q')) == [] and a.oneshot('q') == ''
    assert not a.routing.down and busy.calls == 1 and other.calls == 0, 'a busy route was set aside or handed over'
    assert a.use.total == 5, 'a busy call counted the spend of the call before it'
    plain = Silent(FIRST)
    with pytest.raises(StreamUnsupported, match='first'): list(routed(plain).oneshot_stream('q'))
    assert plain.asked == 0, 'a backend that cannot stream was asked, and its whole reply buffered'
    held = Streams(FIRST, ['a'])
    for bad in (0, -1, True, float('nan'), 'soon'):
        with pytest.raises(ValueError, match='deadline'): routed(held).oneshot_stream('q', deadline=bad)
    no_deadline = Streams(FIRST, ['a']); no_deadline.supports_deadline = False
    with pytest.raises(DeadlineUnsupported, match='first'): list(routed(no_deadline).oneshot_stream('q', deadline=5))
    assert no_deadline.calls == 0 and held.calls == 0
    paid = Streams(FIRST, ['a'], spent=Usage(total=5, cost=.1)); paid.supports_deadline = False
    a = routed(paid)
    assert a.oneshot('q') == 'a' and a.use.total == 5
    with pytest.raises(DeadlineUnsupported): a.oneshot('q', deadline=5)
    with pytest.raises(DeadlineUnsupported): list(a.oneshot_stream('q', deadline=5))
    assert a.use.total == 5, 'a call that sent nothing counted the call before it'


def test_a_timeout_or_cancel_is_typed_and_never_falls_back():
    from rishi.core import OneShotCancelled
    for boom in (Late(1.5, False), OneShotCancelled(1.5, False), OneshotTimeout('first', 3.2, True)):
        first, second = Streams(FIRST, ['a'], boom=boom, spent=Usage(total=4, cost=.2)), Streams(SECOND, ['b'])
        a, got = routed(first, second), []
        with pytest.raises(type(boom) if not isinstance(boom, Late) else OneshotTimeout) as e:
            for t in a.oneshot_stream('q', deadline=5): got.append(t)
        assert got == ['a'] and second.calls == 0 and not a.routing.down and first.problems == [], f'{boom!r} fell back or was recorded as a failure'
        assert e.value is boom or isinstance(e.value.__cause__, Late)
        assert (a.use.total, a.use.cost) == (4, .2), 'what a call that was cut short spent was not counted'
        assert 4 < first.deadlines[0] <= 5, 'the backend was not handed what was left of the deadline'
    assert not first.lock.locked() and first.closed == 1
    sync = Streams(FIRST, boom=None); sync._oneshot = lambda *a, **k: (_ for _ in ()).throw(OneShotCancelled(2.0, True))
    with pytest.raises(OneShotCancelled): routed(sync, Streams(SECOND)).oneshot('q')


def test_one_shots_count_against_the_budget_and_the_one_that_crosses_it_raises():
    for cap, limit, spent, kw in (('max_cost', 1.0, 1.2, dict(max_cost=1.0)), ('max_tokens', 20, 30, dict(max_tokens=20)),
                                  ('max_cost', 1.0, 1.2, dict(session_max_cost=1.0)), ('max_tokens', 20, 30, dict(session_max_tokens=20))):
        be = Streams(FIRST, ['a'], spent=Usage(input=10, output=5, total=15, cost=.6))
        a = routed(be, **kw)
        assert list(a.oneshot_stream('q')) == ['a'], 'the first one-shot was within the budget'
        with pytest.raises(BudgetExceeded) as got: list(a.oneshot_stream('q'))
        e = got.value
        assert (e.cap, e.limit, e.estimated) == (cap, limit, False) and e.spent == pytest.approx(spent) and cap in str(e) and isinstance(e, AgentError)
        assert a.use.total == 30 and a.use.cost == pytest.approx(1.2), 'the call that crossed the budget was not counted'
        calls = be.calls
        with pytest.raises(BudgetExceeded): a.oneshot('q')
        with pytest.raises(BudgetExceeded): list(a.oneshot_stream('q'))
        assert be.calls == calls, 'a provider was called with the budget spent'
    exact = Streams(FIRST, ['a'], spent=Usage(total=5, cost=1.0))
    a = routed(exact, max_cost=1.0)
    assert a.oneshot('q') == 'a' and a.use.cost == 1.0, 'spending exactly the budget is within it'
    with pytest.raises(BudgetExceeded) as got: a.oneshot('q')
    assert (got.value.spent, got.value.limit) == (1.0, 1.0) and exact.calls == 1, 'a call began with the budget reached'


def test_a_route_that_failed_before_its_first_text_still_spent_its_prompt_and_a_budget_it_crossed_ends_the_search():
    early, spare = Streams(FIRST, boom=RuntimeError('refused'), spent=Usage()), Streams(SECOND, ['z'])
    a = routed(early, spare)
    assert list(a.oneshot_stream('q' * 40, 'brief')) == ['z']
    assert a.use.total == early.count_tokens('q' * 40) + early.count_tokens('brief') > 0, 'the prompt of a failed call was counted as nothing'
    early, spare = Streams(FIRST, boom=RuntimeError('refused'), spent=Usage()), Streams(SECOND, ['z'])
    a = routed(early, spare, max_tokens=1)
    with pytest.raises(BudgetExceeded): list(a.oneshot_stream('q' * 40))
    assert spare.calls == 0, 'the next route was asked after the budget was crossed'


def test_different_routes_overlap_even_with_a_budget():
    barrier = threading.Barrier(2, timeout=3)
    class Together(Streams):
        def _oneshot(self, prompt, sp, max_tokens, deadline=None):
            barrier.wait()
            return super()._oneshot(prompt, sp, max_tokens, deadline)
    first = Together(FIRST, ['a'], spent=Usage(total=3, cost=.1))
    second = Together(SECOND, ['b'], spent=Usage(total=7, cost=.2))
    a = routed(first, second, max_cost=100)
    a._be_or_none = lambda job: first if job == 'guide' else second
    with ThreadPoolExecutor(2) as pool:
        calls = [pool.submit(a.oneshot, 'q', job=job) for job in ('guide', 'tutor')]
        assert [call.result() for call in calls] == ['a', 'b']
    assert a.use.total == 10 and a.use.cost == pytest.approx(.3)


def test_a_stream_is_stopped_when_its_text_count_passes_a_token_budget():
    be = Streams(FIRST, ['wxyz'] * 10, spent=Usage())   # a hosted model that reports nothing for a stream it never finished
    a, got = routed(be, max_tokens=5), []
    with pytest.raises(BudgetExceeded) as e:
        for t in a.oneshot_stream('q'): got.append(t)
    assert got == ['wxyz'] * 3 and (e.value.cap, e.value.limit, e.value.estimated, e.value.stopped) == ('max_tokens', 5, True, True), e.value
    assert len(be.given) == 4 and be.closed == 1 and not be.lock.locked(), 'the stream was read on, or left open'
    assert a.use.total > 0 and a.use.estimated, 'what the stopped stream spent was not counted'


def test_a_partial_reply_with_no_reported_usage_is_estimated_and_a_reported_cost_wins():
    be = Streams(FIRST, ['alpha ', 'beta'], spent=Usage())
    a = routed(be, est_rate=1e-5)
    it = a.oneshot_stream('q' * 40, 'brief')
    next(it); it.close()
    want = be.count_tokens('q' * 40) + be.count_tokens('brief') + be.count_tokens('alpha ')
    assert a.use.total == want and a.use.estimated and a.use.cost == pytest.approx(want * 1e-5) and a.estimated == pytest.approx(a.use.cost)
    stale = Streams(FIRST, ['x' * 400, 'y'], spent=Usage(input=10, output=1, total=11))   # usage that trails the text already sent
    a = routed(stale, est_rate=1e-5)
    it = a.oneshot_stream('q'); next(it); it.close()
    assert a.use.total == 10 + stale.count_tokens('x' * 400) and a.use.estimated
    paid = Streams(SECOND, ['x'], spent=Usage(input=4, output=1, total=5, cost=.3))
    a = routed(paid, est_rate=1.0)
    assert list(a.oneshot_stream('q')) == ['x'] and a.use.cost == .3 and a.estimated == 0 and not a.use.estimated


def test_concurrent_one_shots_lose_no_spend():
    a, _ = fake_agent()
    mine = threading.local()
    a._be_or_none = lambda job: mine.be
    def work():
        mine.be = Streams(FIRST, ['a'], spent=Usage(input=10, output=5, total=15, cost=.01))
        for _ in range(30): list(a.oneshot_stream('q'))
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(8) as pool:
            for f in [pool.submit(work) for _ in range(8)]: f.result()   # a failure in a thread raises here
    finally: sys.setswitchinterval(old)
    assert a.use.total == 8 * 30 * 15 and a.use.cost == pytest.approx(8 * 30 * .01), 'a fold was lost'
    shared = Streams(FIRST, ['a'], spent=Usage(input=10, output=5, total=15, cost=.01))
    b = routed(shared)
    def hammer():
        for _ in range(30): b.oneshot('q'); list(b.oneshot_stream('q'))
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(8) as pool:
            for f in [pool.submit(hammer) for _ in range(8)]: f.result()
    finally: sys.setswitchinterval(old)
    assert b.use.total == shared.calls * 15 > 0, 'a call was counted twice or not at all with callers sharing one backend'


def test_a_smaller_final_report_does_not_erase_partial_spend():
    class Reports(Streams):
        def __init__(self):
            super().__init__(FIRST, ['a', 'b'])
            self.reports = iter([Usage(total=10, cost=.4), Usage(total=5, cost=.2), Usage(total=5, cost=.2)])
        def _reported(self): return next(self.reports)
    a = routed(Reports())
    assert list(a.oneshot_stream('q')) == ['a', 'b']
    assert a.use.total == 10 and a.use.cost == .4


def test_two_callers_keep_distinct_reports_from_one_backend():
    first_fold, second_fold = threading.Event(), threading.Event()
    class Different(Streams):
        def _oneshot(self, prompt, sp, max_tokens, deadline=None):
            self.spent = Usage(total=int(prompt), cost=int(prompt) / 100)
            return super()._oneshot(prompt, sp, max_tokens, deadline)
    be = Different(FIRST, ['answer'])
    a = routed(be)
    fold = a._one_fold
    def held_fold(spent, rate):
        if spent[0].total == 3:
            first_fold.set()
            assert second_fold.wait(3)
        else:
            assert first_fold.wait(3)
            second_fold.set()
        return fold(spent, rate)
    a._one_fold = held_fold
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(a.oneshot, '3')
        assert first_fold.wait(3)
        second = pool.submit(a.oneshot, '7')
        assert first.result() == second.result() == 'answer'
    assert a.use.total == 10 and a.use.cost == pytest.approx(.1)


def test_one_shots_leave_the_turn_alone_and_the_next_ask_counts_only_itself(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    be = Streams(FIRST, ['t'], spent=Usage(input=2, output=1, total=3, cost=.1), replies=['hi'])
    a._be = a._be_or_none = lambda job='turn': be
    turn = lambda: (list(a.history), a._budget_hit, a._budget_cap, a.turn_use.total, dict(a._usage_seen), a.current_turn_id)
    before = turn()
    list(a.oneshot_stream('q')); a.oneshot('q')
    assert a.use.total == 6 and turn() == before, 'a one-shot changed the turn'
    a.ask('hello')
    assert a.turn_use.total == 15 and a.use.total == 6 + 15, 'the turn counted a one-shot again, or missed itself'


class Held:
    "A chat that holds one `UsageStats` and fills it in as its stream runs, rather than replacing it."
    oneshot_stream_ok = True
    def __init__(self, model_id, **kw): self.hist, self.oneshot_use = [], UsageStats()
    def oneshot_stream(self, prompt, sp='', think=None, max_tokens=None, deadline=None):
        def gen():
            yield 'a'
            self.oneshot_use.prompt_tokens = 7   # the first report, after the first text
            yield 'b'
            self.oneshot_use.completion_tokens, self.oneshot_use.total_tokens = 1, 8
            yield 'c'
        return gen()


def test_a_chat_that_fills_in_one_usage_object_is_counted_from_what_it_held():
    be = RishiBackend(ModelSpec('gpt', 'remote', 'gpt-5.1', 272_000))
    a = routed(be)
    with use_chat(Held):
        it = a.oneshot_stream('q')
        assert (next(it), next(it)) == ('a', 'b')
        it.close()
        first_out = be.count_tokens('ab')
        assert (a.use.input, a.use.output) == (7, first_out) and a.use.estimated, 'a stream closed after its first report lost it'
        assert ''.join(a.oneshot_stream('q')) == 'abc'
    assert (a.use.input, a.use.output) == (14, first_out + 1), 'a second call was not counted from what the chat held'


def test_rishis_remote_stream_reaches_the_agent_through_its_public_method(monkeypatch):
    remote = pytest.importorskip('rishi.remote')
    if not hasattr(remote.RemoteChat, 'oneshot_stream'): pytest.skip('the installed rishi predates oneshot_stream')
    from aidialog.msg_parts import Msg, Text
    from fastllm.types import Completion, Usage as Fast
    done = Completion(model='m', usage=Fast(prompt_tokens=7, completion_tokens=2), message=Msg(role='assistant', content=[Text(text='Hello')]))
    closed = []
    def stream(*parts, hold=False):
        async def acomplete(msgs, model, **kw):
            async def go():
                try:
                    for p in parts: yield p
                    if hold: await asyncio.Event().wait()
                finally: closed.append(True)
            return go()
        return acomplete
    be = RishiBackend(ModelSpec('gpt', 'remote', 'gpt-5.1', 272_000))
    a = routed(be)
    monkeypatch.setattr(remote, 'acomplete', stream(Text(text='Hel'), Text(text='lo'), done))
    assert list(a.oneshot_stream('hi')) == ['Hel', 'lo'] and be.supports_stream and not be.supports_deadline
    assert (a.use.input, a.use.output) == (7, 2) and closed == [True]
    monkeypatch.setattr(remote, 'acomplete', stream(Text(text='Hel'), hold=True))
    closed.clear()
    it = a.oneshot_stream('hi')
    assert next(it) == 'Hel' and closed == [] and be.lock.locked()
    it.close()
    assert closed == [True] and not be.lock.locked()
    want = 9 + be.count_tokens('hi') + be.count_tokens('') + be.count_tokens('Hel')   # the first call's reported 7 and 2, then the prompt and the text sent
    assert a.use.total == want and a.use.estimated, 'a stream closed early, with no usage reported, was not estimated'
    with pytest.raises(DeadlineUnsupported): a.oneshot_stream('hi', deadline=5).__next__()