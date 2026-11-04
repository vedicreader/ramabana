"`model_agent()`: an `Agent` that only calls the model, without the eleven options an app spelled out to turn the harness off."
from ramabana.agent import model_agent
from ramabana.testing import FakeBackend
from ramabana.tools import WRITE_TOOLS


def test_it_has_no_tool_that_writes():
    a = model_agent()
    names = {t.__name__ for t in a.tools}
    assert not names & set(WRITE_TOOLS) and a.readonly


def test_approvals_are_refused():
    a = model_agent()
    assert a.approvals.mode == 'ask' and a.approvals.no_listener == 'refuse'


def test_oneshot_runs_through_a_fake_backend():
    a, b = model_agent(sp='You are a tutor.'), FakeBackend()
    a._be = a._be_or_none = lambda job='turn': b
    assert a.oneshot('hello') == 'ONESHOT:hello'


def test_an_option_given_wins():
    a = model_agent('claude-haiku-5-5', max_cost=2., only_tools=['submit_result'])
    assert a.routing.turn == 'claude-haiku-5-5' and a.max_cost == 2. and set(a.only_tools) == {'submit_result'}
