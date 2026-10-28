"A Claude Code turn reports its cost only when it ends, so its dollar limits reach Claude Code as `max_budget_usd`, current at each turn, and a run the budget stopped is recorded with what it cost."
from types import SimpleNamespace as NS
from ramabana import agent
from ramabana.runtime import Usage
from ramabana.testing import FakeBackend, fake_agent

class Chat:
    def __init__(self): self.set = []
    def set_opts(self, **kw): self.set.append(kw)

def claude_backend(): return NS(spec=NS(runtime='claude'), chat=Chat(), start=lambda: True)

def test_a_claude_turn_gets_what_is_left_of_its_turn_and_session_limits():
    a, _ = fake_agent(max_cost=3.0, session_max_cost=5.0)
    b = claude_backend()
    a._claude_budget(b)
    a.use = Usage(cost=4.0)   # an earlier turn spent $4 of the session's $5
    a._claude_budget(b)
    assert b.chat.set == [{'max_budget_usd': 3.0}, {'max_budget_usd': 1.0}], b.chat.set   # a budget set once at build time counted the earlier turns

def test_no_limit_clears_the_budget_and_other_models_get_none():
    a, _ = fake_agent()
    b = claude_backend(); a._claude_budget(b)
    assert b.chat.set == [{'max_budget_usd': None}]
    other = NS(spec=NS(runtime='remote'), chat=Chat(), start=lambda: True)
    a.max_cost = 3.0; a._claude_budget(other)
    assert other.chat.set == []   # a urai backend stops through the budget callback after each step

def test_a_turn_sets_the_budget_before_it_sends(monkeypatch):
    a, be = fake_agent(replies=['ok'], max_cost=3.0)
    seen = []
    monkeypatch.setattr(agent.Agent, '_claude_budget', lambda self, b: seen.append(b))
    a.ask('go')
    assert seen == [be]

class Stopped(Exception):
    budget, usage = True, {'cost': 8.4}

class Paid(FakeBackend):
    "Claude Code that stops at its budget after spending $8.40."
    spent = 0.
    def _send(self, msg, **kw):
        self.spent = 8.4
        raise Stopped('claude stopped by its budget: it spent $8.40, past max_budget_usd')
    def _usage(self): return Usage(model=self.spec.model_id, cost=self.spent)

def test_a_run_the_budget_stopped_is_a_budget_row_with_its_cost():
    a, _ = fake_agent(max_cost=3.0)
    be = Paid(); a._be = lambda job='turn': be; a._be_or_none = lambda job='turn': be
    a.ask('go')
    row = a.history[-1]
    assert row['state'] == 'budget' and 'budget' in row['error'] and row['usage']['cost'] == 8.4, row   # it showed failed and $0

def test_a_claude_backend_is_built_with_the_turn_limit_for_an_older_rishi(monkeypatch):
    from ramabana.agent import Agent
    from ramabana.testing import MemHost
    got = []
    monkeypatch.setattr(agent, 'make_backend', lambda spec, **k: got.append((spec, k)) or FakeBackend(spec))
    Agent(MemHost(), extensions=False, subagents=False, model='sonnet', max_cost=3.0)._be('turn')
    assert got[-1][0].runtime == 'claude' and got[-1][1]['opts']['max_budget_usd'] == 3.0
