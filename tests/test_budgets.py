"A host caps what a turn, or a whole session, may spend; the turn past it is stopped and recorded as `budget`."
import json
from types import SimpleNamespace

import pytest
from fastcore.script import anno_parser
import ramabana.cli as cli

from urai.core import UsageStats

from ramabana.agent import TurnFailed, TurnResult
from ramabana.core import resolve
from ramabana.runtime import Usage, current_run
from ramabana.testing import FakeBackend, fake_agent

#: a hosted model fastllm has no price for
UNPRICED = resolve('nosuch/model')


class Spending(FakeBackend):
    "A model loop of `steps` steps, each spending `per` tokens and, when `paid`, `per / 1000` dollars, that runs the chat callbacks after each response."
    def __init__(self, owner, steps, per, paid=True, obey=True, **kw):   # `obey` False keeps spending after a cancel
        super().__init__(**kw)
        self.owner, self.steps, self.per, self.paid, self.obey, self.ran = owner, steps, per, paid, obey, 0
    def _send(self, msg, **kw):
        self.sent.append(msg)
        use = UsageStats()
        for _ in range(self.steps):
            if self.obey and (run := current_run()) is not None and run.cancelled: break
            self.ran += 1
            use = use + UsageStats(total_tokens=self.per, cost=self.per / 1000 if self.paid else 0.)
            for cb in getattr(self.owner, '_chat_callbacks', {}).values():
                c = cb(); c.chat = SimpleNamespace(use=use); c.after_response()
        return 'spent'
    def _usage(self): return Usage(model=self.spec.model_id, total=self.per * self.ran, cost=self.per * self.ran / 1000 if self.paid else 0.)

def _agent(tmp_path, steps=10, per=1000, paid=True, spec=None, **budgets):
    a, _ = fake_agent(cfg=tmp_path, **budgets)
    be = Spending(a, steps, per, paid, **({} if spec is None else {'spec': spec}))
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


def test_a_model_that_reports_no_cost_is_stopped_by_a_dollar_budget_at_an_estimated_price(tmp_path):
    a, be = _agent(tmp_path, per=1000, paid=False, spec=UNPRICED, max_cost=0.025)   # $10 a million tokens: $0.01 a step
    r = a.ask('go', result=True)
    assert r.state == 'budget' and be.ran == 3, (r, be.ran)
    assert r.budget == 'cost' and r.estimated is True and TurnResult(estimated=True).estimated, r
    assert 'estimated dollars this turn' in r.error, r.error
    saved = json.loads(a.history_path.read_text().splitlines()[-1])
    assert saved['budget'] == 'cost' and saved['usage']['estimated'] and saved['usage']['cost'] == pytest.approx(0.03), saved['usage']
    assert a.use.estimated and a.use.cost == pytest.approx(0.03) and a.use.total == 3000, a.use
    assert a.estimated == pytest.approx(0.03), 'the agent kept no running total of its estimates'
    r = a.ask('again', result=True)
    assert a.use.total == 6000 and a.use.cost == pytest.approx(0.06), 'a stopped turn is counted once, in its own row'


def test_a_reported_cost_wins_and_est_rate_prices_the_rest(tmp_path):
    a, be = _agent(tmp_path, max_cost=2.5, est_rate=1.0)   # reports $1 a step; the rate would make it $1000
    r = a.ask('go', result=True)
    assert r.state == 'budget' and be.ran == 3 and not r.estimated and r.usage['cost'] == pytest.approx(3.0), r
    seen = []
    a, be = _agent(tmp_path, paid=False, spec=UNPRICED, max_cost=2.5, est_rate=lambda spec: seen.append(spec) or 1e-3)
    assert a.ask('go', result=True).budget == 'cost' and be.ran == 3 and seen[0] is UNPRICED
    a, be = _agent(tmp_path, steps=4, paid=False, max_cost=0.001)   # a local model is free
    r = a.ask('go', result=True)
    assert r.state == 'complete' and r.budget is None and r.usage['cost'] == 0 and not r.estimated, r
    a, be = _agent(tmp_path, paid=False, max_cost=2.5, est_rate=1e-3)   # unless `est_rate` prices it
    r = a.ask('go', result=True)
    assert r.budget == 'cost' and be.ran == 3 and r.estimated, r
    a, be = _agent(tmp_path, paid=False, spec=UNPRICED, max_cost=0.025, est_rate=lambda spec: None)   # None asks for the $10 a million default
    assert a.ask('go', result=True).budget == 'cost' and be.ran == 3 and a.estimated == pytest.approx(0.03)


def test_a_turn_past_its_token_budget_stops_at_the_step_that_crossed_it(tmp_path):
    a, be = _agent(tmp_path, max_tokens=2500)
    r = a.ask('go', result=True)
    assert r.state == 'budget' and r.budget == 'tokens' and be.ran == 3, (r, be.ran)
    assert a.history[-1]['state'] == 'budget'
    with pytest.raises(TurnFailed) as got: a.ask('again', strict=True)
    assert got.value.result.state == 'budget' and got.value.result.budget == 'tokens', 'every turn gets the same allowance'


class Calling(FakeBackend):
    "A turn that calls the agent's first tool `n` times, then replies."
    def __init__(self, owner, n, **kw):
        super().__init__(**kw)
        self.owner, self.n, self.got = owner, n, []
    def _send(self, msg, **kw):
        self.sent.append(msg)
        self.got = [self.owner.tools[0]() for _ in range(self.n)]
        return 'what I found'

class Stepped(FakeBackend):
    "A turn whose chat refused a tool call at its `max_steps`, with the state urai's tool loop leaves."
    max_steps = None
    def _send(self, msg, **kw):
        self.sent.append(msg)
        self.chat = SimpleNamespace(max_steps=self.max_steps, _steps=self.max_steps, _budget_exceeded=True)
        return 'out of steps'

def test_tool_call_and_step_caps_end_the_turn_as_budget_and_name_their_cap(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, max_tool_calls=20)   # the least `max_tool_calls` takes
    be = Calling(a, 21); a._be = a._be_or_none = lambda job='turn': be
    r = a.ask('go', result=True)
    assert 'budget exhausted' in be.got[-1] and 'budget exhausted' not in be.got[-2], be.got[-2:]
    assert r.state == 'budget' and r.budget == 'tool_calls' and r.reply.startswith('what I found') and '21 tool calls' in r.error, r
    a, _ = fake_agent(cfg=tmp_path, max_steps=8)   # the least `max_steps` takes
    be = Stepped(); a._be = a._be_or_none = lambda job='turn': be
    r = a.ask('go', result=True)
    assert r.state == 'budget' and r.budget == 'steps' and '8 tool-call steps' in r.error, r
    a, _ = fake_agent(cfg=tmp_path, replies=['done'])
    r = a.ask('go', result=True)
    assert r.state == 'complete' and r.budget is None and a.history[-1]['budget'] is None, r


class Failing(Calling):
    "A turn that runs its tool calls, then fails at the provider."
    def _send(self, msg, **kw):
        super()._send(msg, **kw)
        raise RuntimeError('provider down')

class Interrupted(Calling):
    "A turn that runs its tool calls, then is cancelled by the user."
    def _send(self, msg, **kw):
        out = super()._send(msg, **kw)
        current_run().request_cancel()
        return out

def test_a_resume_gives_back_a_turn_a_soft_cap_ended_and_not_one_a_hard_cap_stopped(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, max_tool_calls=20)
    be = Calling(a, 21); a._be = a._be_or_none = lambda job='turn': be
    assert a.ask('soft', result=True).budget == 'tool_calls'
    assert [t['prompt'] for t in a.replayed_turns(a.session_id)] == ['soft'], 'a finished reply was dropped from the resume'
    h, _ = _agent(tmp_path, max_tokens=2500)
    assert h.ask('hard', result=True).budget == 'tokens'
    assert h.replayed_turns(h.session_id) == [], 'an unfinished reply came back'

def test_a_provider_error_or_a_user_cancel_outranks_a_soft_cap(tmp_path):
    for turn, state in ((Failing, 'failed'), (Interrupted, 'cancelled')):
        a, _ = fake_agent(cfg=tmp_path, max_tool_calls=20)
        be = turn(a, 21); a._be = a._be_or_none = lambda job='turn': be
        r = a.ask('go', result=True)
        assert r.state == state and r.budget is None and a.history[-1]['state'] == state, (turn.__name__, r)

class Budgeted(FakeBackend):
    "A turn a token budget stopped, whose model then reports its own budget stop."
    def __init__(self, owner, **kw):
        super().__init__(**kw)
        self.owner = owner
    def _send(self, msg, **kw):
        self.owner._over('tokens', 'stopped by its budget: 3,000 tokens this turn, past 2,500')
        e = RuntimeError('model budget')
        e.budget = True
        raise e

def test_a_model_budget_stop_keeps_a_token_cap_that_already_stopped_the_turn(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    be = Budgeted(a); a._be = a._be_or_none = lambda job='turn': be
    r = a.ask('go', result=True)
    assert r.state == 'budget' and r.budget == 'tokens', r

def test_urai_leaves_the_state_the_step_cap_reads():
    from fastcore.foundation import L
    from urai.loop import ToolLoopMixin
    from ramabana.agent import _steps_over
    class Loop(ToolLoopMixin):
        cbs, approve, max_steps, turn_tc = L(), None, 2, None
        _steps, _budget_exceeded = 0, False
    chat = Loop()
    asked = [chat._approve1({'function': {'name': 'view_file', 'arguments': '{}'}})[0] for _ in range(2)]
    assert asked == [True, True] and _steps_over(SimpleNamespace(chat=chat)) is None, 'the cap fired before a call was refused'
    assert chat._approve1({'function': {'name': 'view_file', 'arguments': '{}'}})[0] is False
    assert _steps_over(SimpleNamespace(chat=chat)) == (2, 2)

def test_a_bad_est_rate_fails_before_the_provider_and_never_costs_a_row(tmp_path):
    for bad in (float('nan'), -1, True, 'dear'):
        with pytest.raises(ValueError, match='est_rate'): fake_agent(est_rate=bad)
    for rate in (lambda spec: 1 / 0, lambda spec: 'dear', lambda spec: float('inf')):
        a, be = _agent(tmp_path, paid=False, spec=UNPRICED, max_cost=1, est_rate=rate)
        r = a.ask('go', result=True)
        assert r.state == 'failed' and be.sent == [] and a.history[-1]['turn_id'] == r.turn_id, (r, be.sent)
    a, be = _agent(tmp_path, paid=False, spec=UNPRICED, est_rate=lambda spec: 1 / 0)   # no dollar budget needs the price
    r = a.ask('go', result=True)
    assert r.state == 'complete' and r.usage['total'] == 10000 and not r.estimated and 'est_rate failed' in a.note, (r, a.note)


def test_est_rate_prices_each_model_once_a_turn_for_the_check_the_steps_and_the_fold(tmp_path):
    calls = []
    def counted(spec):
        calls.append(spec)
        return 1e-5
    a, be = _agent(tmp_path, steps=4, paid=False, spec=UNPRICED, max_cost=1, est_rate=counted)
    assert a.ask('go', result=True).state == 'complete' and len(calls) == 1, len(calls)
    a.ask('again', result=True)
    assert len(calls) == 2, 'a new turn reused the last turn\'s rate'


def test_the_first_hard_cap_a_turn_crosses_is_the_one_recorded(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, max_cost=1.5, max_tokens=2500)   # step 2 crosses the dollar cap, step 3 the token cap
    be = Spending(a, 3, 1000, obey=False); a._be = a._be_or_none = lambda job='turn': be
    r = a.ask('go', result=True)
    assert be.ran == 3 and r.state == 'budget' and r.budget == 'cost' and 'dollars this turn' in r.error, (r, be.ran)


def test_a_session_budget_counts_what_earlier_turns_spent(tmp_path):
    a, be = _agent(tmp_path, session_max_cost=2.5)
    a.use = Usage(total=2000, cost=2.0)   # what earlier turns spent
    r = a.ask('go', result=True)
    assert r.state == 'budget' and be.ran == 1


def test_without_budgets_nothing_is_watched_and_the_turn_runs_out(tmp_path):
    a, be = _agent(tmp_path, steps=4)
    assert a.ask('go', result=True).state == 'complete' and be.ran == 4
    assert 'budget' not in getattr(a, '_chat_callbacks', {})


@pytest.mark.parametrize('flags, limit, steps', [([], None, 4), (['--max-cost', '1.5'], 1.5, 2)])
def test_cli_cost_limit_reaches_the_agent_and_stops_a_spending_turn(tmp_path, monkeypatch, flags, limit, steps):
    made = []
    def build(roots, **kw):
        a, be = _agent(tmp_path, steps=4, max_cost=kw.get('max_cost'))
        a.settle = lambda: ''
        made.append((a, be))
        return a, a.host
    monkeypatch.setattr(cli, 'mk_agent', build)
    monkeypatch.setattr(cli.setup, 'LAUNCHED', True)
    monkeypatch.setattr(cli, 'needs_setup', lambda routing: '')
    args = vars(anno_parser(cli.main.__wrapped__, pos=['prompt']).parse_args(['go', '--approve', 'auto', *flags]))
    for k in ('pdb', 'xtra'): args.pop(k, None)
    with pytest.raises(SystemExit): cli.main(**args)
    a, be = made[0]
    assert a.max_cost == limit and be.ran == steps
    assert a.history[-1]['state'] == ('complete' if limit is None else 'budget')
    if limit is not None: assert 'stopped by its budget' in a.history[-1]['error']
