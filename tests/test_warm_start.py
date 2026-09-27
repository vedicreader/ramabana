"""A fresh session is seeded with dhrona's accepted rounds whose calls bind to its tools; nothing else is.

The rounds are worked examples of the tool dialect (search vs grep, a refused approval, a git flow).
They cost a few hundred tokens and only pay on a conversation that has none yet, so a resumed
session, a small window and `--no-warm` all get an empty chat.
"""
import inspect
import json
import sys

import pytest

dhrona = pytest.importorskip('dhrona')

from ramabana.agent import WARM_ROUNDS, Agent
from ramabana.core import Budget
from ramabana.testing import FakeBackend, FullHost, MemHost, fake_agent


def names(hist): return [tc.name for m in hist if m.get('tool_calls') for tc in m['tool_calls']]


@pytest.fixture
def full(monkeypatch):
    "The fake `SPEC` is a 1k window, whose budget inlines nothing; a warm start needs a full one."
    monkeypatch.setattr(Agent, 'budget', property(lambda self: Budget()))


def _turn(session, prompt, reply, model='gpt-mini'):
    return {'at': 0, 'session': session, 'prompt': prompt, 'reply': reply, 'model': model, 'activity': []}


def test_a_fresh_session_is_seeded_once_with_rounds_whose_calls_bind_to_its_tools(tmp_path, full):
    a, be = fake_agent(cfg=tmp_path, replies=['ok', 'ok'])
    a.ask('hello')
    seeded = be.hist_[:-2]                                  # everything before this turn's user message and reply
    assert seeded and seeded[0]['role'] == 'user' and be.hist_[-2]['content'].startswith('hello')
    assert set(names(seeded)) <= {t.__name__ for t in a.tools}, 'nothing the model cannot call'
    used = [r['name'] for r in a.warm_report['used']]
    assert 0 < len(used) <= WARM_ROUNDS and 'search-choice' in used
    assert any(r['name'] == 'git-flow' and 'git_status' in r['reason'] for r in a.warm_report['skipped'])
    assert a.history[-1]['plan']['warm'] == used             # the turn record says what it was seeded with
    saved = [json.loads(l) for l in a.history_path.read_text().splitlines()][-1]
    assert saved['plan']['warm'] == used
    assert a.checkpoints[a.history[-1]['turn_id']]['before'][:len(seeded)] == seeded   # a /rewind to before turn 1 keeps them
    a.ask('again')
    assert a.warm_start() == [] and be.hist_[:len(seeded)] == seeded and 'warm' not in a.history[-1]['plan']   # once


def test_a_resumed_session_is_not_seeded(tmp_path, full):        # Review Focus 1
    b, be2 = fake_agent(cfg=tmp_path, replies=['ok'])
    b.history = [_turn('s1', 'start', 'first')]              # a registered model name, as `test_resume` does
    b.resume_session('s1')
    b.ask('again')
    assert be2.hist_[0]['content'] == 'start' and not names(be2.hist_)
    assert b.warm_report['used'] == [] and 'warm' not in b.history[-1]['plan']


def test_changing_the_model_before_the_first_prompt_still_seeds(tmp_path, full, monkeypatch):
    "`set_model` carries the conversation across backends; before turn 1 there is none to carry, and the session is still fresh."
    from ramabana import agent as agent_mod
    made = []
    def build(spec, **kw):
        made.append(FakeBackend(spec, replies=['ok'], **kw)); return made[-1]
    monkeypatch.setattr(agent_mod, 'make_backend', build)
    a = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), model='gemma-e2b', cfg=tmp_path, extensions=False, subagents=False)
    a.set_model('gemma-12b')                                 # a lazy backend: nothing has started yet
    assert a.warm_start(), 'a fresh session, whatever model it starts on'   # a frontend may seed before the first prompt
    a.ask('hello')
    be = made[-1]
    assert be.hist_[0]['content'] != 'hello' and be.hist_[-2]['content'].startswith('hello') and a.warm_report['used']


def test_no_warm_and_no_dhrona_leave_the_chat_empty(monkeypatch, full):    # Review Focus 2
    a, be = fake_agent(warm=False, replies=['ok']); a.ask('x')
    assert len(be.hist_) == 2 and a.warm_start() == []
    monkeypatch.setitem(sys.modules, 'dhrona', None); monkeypatch.setitem(sys.modules, 'dhrona.core', None)
    h = FullHost(files={'a.py': 'x = 1\n'})
    a, be = fake_agent(h, replies=['ok']); a.ask('x')
    assert len(be.hist_) == 2 and a.warm_start() == []
    assert any('no warm start' in n and 'dhrona' in n for n in h.notes), h.notes


def test_a_small_window_skips_the_seeds():
    a, be = fake_agent(replies=['ok'])
    assert not a.budget.inline                              # the fake `SPEC` is a 1k window
    a.ask('x')
    assert len(be.hist_) == 2 and a.warm_report['used'] == []


def test_sub_agents_are_not_seeded(full):                    # Review Focus 3
    a, be = fake_agent(replies=['ok']); a.ask('x')
    tools = {t.__name__: t for t in a.tools}
    tools['delegate_search'](['q'])
    assert be.spawned and not names(be.spawned[0].hist_)


def test_the_cli_and_mk_agent_carry_the_switch(tmp_path):
    from ramabana import cli
    ps = inspect.signature(cli.main).parameters
    assert ps['warm'].default is True and ps['optin'].default == ''
    a, _ = cli.mk_agent([str(tmp_path)], approve='none', web=False, warm=False, optin=('exhash',), host_kw=dict(index=False))
    assert a.warm is False and a.optin == ('exhash',)
