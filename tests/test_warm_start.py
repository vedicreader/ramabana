"""Asked to (`--warm`), a fresh session is seeded with dhrona's accepted rounds whose calls bind to its tools.

The rounds are worked examples of the tool dialect (search vs grep, a refused approval, a git flow).
They are off unless asked for: each shows one call per message and a terse narration line, which a
current model copies, and the briefing already says what they demonstrate. A resumed session and a
small window get an empty chat even when asked.
"""
import json
import sys

import pytest

dhrona = pytest.importorskip('dhrona')

from ramabana.agent import WARM_ROUNDS, Agent
from ramabana.core import Budget
from ramabana.testing import FullHost, fake_agent


def names(hist): return [tc.name for m in hist if m.get('tool_calls') for tc in m['tool_calls']]


@pytest.fixture
def full(monkeypatch):
    "The fake `SPEC` is a 1k window, whose budget inlines nothing; a warm start needs a full one."
    monkeypatch.setattr(Agent, 'budget', property(lambda self: Budget()))


def test_a_fresh_session_is_seeded_once_with_rounds_whose_calls_bind_to_its_tools(tmp_path, full):
    a, be = fake_agent(cfg=tmp_path, replies=['ok', 'ok'], warm=True)
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


def test_no_warm_and_no_dhrona_leave_the_chat_empty(monkeypatch, full):    # Review Focus 2
    for kw in ({'warm': False}, {}):                       # off unless asked, in every profile
        a, be = fake_agent(replies=['ok'], **kw); a.ask('x')
        assert len(be.hist_) == 2 and a.warm_start() == [] and a.warm is False
    monkeypatch.setitem(sys.modules, 'dhrona', None); monkeypatch.setitem(sys.modules, 'dhrona.core', None)
    h = FullHost(files={'a.py': 'x = 1\n'})
    a, be = fake_agent(h, replies=['ok'], warm=True); a.ask('x')
    assert len(be.hist_) == 2 and a.warm_start() == []
    assert any('no warm start' in n and 'dhrona' in n for n in h.notes), h.notes
