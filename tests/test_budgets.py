"A host caps what a turn, or a whole session, may spend; the turn past it is stopped and recorded as `budget`."
from types import SimpleNamespace

import pytest
from fastcore.script import anno_parser
import ramabana.cli as cli

from urai.core import UsageStats

from ramabana.runtime import Usage, current_run
from ramabana.testing import FakeBackend, fake_agent


class Spending(FakeBackend):
    "A model loop of `steps` steps, each spending `per` tokens and `per / 1000` dollars, that runs the chat callbacks after each response."
    def __init__(self, owner, steps, per, **kw):
        super().__init__(**kw)
        self.owner, self.steps, self.per, self.ran = owner, steps, per, 0
    def _send(self, msg, **kw):
        self.sent.append(msg)
        use = UsageStats()
        for _ in range(self.steps):
            if (run := current_run()) is not None and run.cancelled: break
            self.ran += 1
            use = use + UsageStats(total_tokens=self.per, cost=self.per / 1000)
            for cb in getattr(self.owner, '_chat_callbacks', {}).values():
                c = cb(); c.chat = SimpleNamespace(use=use); c.after_response()
        return 'spent'

def _agent(tmp_path, steps=10, per=1000, **budgets):
    a, _ = fake_agent(cfg=tmp_path, **budgets)
    be = Spending(a, steps, per)
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


def test_a_turn_past_its_token_budget_stops_at_the_step_that_crossed_it(tmp_path):
    a, be = _agent(tmp_path, max_tokens=2500)
    r = a.ask('go', result=True)
    assert r.state == 'budget' and be.ran == 3, (r, be.ran)
    assert a.history[-1]['state'] == 'budget'
    r = a.ask('again', result=True)
    assert r.state == 'budget', 'every turn gets the same allowance'


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
