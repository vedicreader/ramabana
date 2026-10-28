"A Claude Code turn reports its cost only when it ends, so `max_cost` has to reach Claude Code as `max_budget_usd`, or nothing stops the run."
from ramabana import agent
from ramabana.agent import Agent
from ramabana.testing import FakeBackend, MemHost

def _built(monkeypatch, **kw):
    got = []
    monkeypatch.setattr(agent, 'make_backend', lambda spec, **k: got.append((spec, k)) or FakeBackend(spec))
    a = Agent(MemHost(), extensions=False, subagents=False, **kw)
    a._be('turn')
    return got[-1]

def test_a_claude_turn_gets_its_dollar_limit_as_claude_codes_budget(monkeypatch):
    spec, kw = _built(monkeypatch, model='sonnet', max_cost=3.0)
    assert spec.runtime == 'claude' and kw['opts']['max_budget_usd'] == 3.0, kw   # a nightly replay passed $28 against --max-cost 8

def test_no_limit_and_other_models_send_no_budget(monkeypatch):
    assert 'opts' not in _built(monkeypatch, model='sonnet')[1]
    spec, kw = _built(monkeypatch, model='gpt-6-luna', max_cost=3.0)
    assert spec.runtime != 'claude' and 'opts' not in kw   # a urai backend stops through the budget callback after each step
