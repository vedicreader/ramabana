"""Tests for the per-model briefing budget.

The arithmetic itself is checked in `nbs/00_core.ipynb`, where it can be read. What is here is
the *wiring*: that a small window actually reaches `tools_for` and `system_prompt`, that a
model change rebuilds what was sized to the old one, and that nothing is withheld from a model
whose window we could not read.

Nothing here loads a model. A `ModelSpec` is the whole input the budget takes, so a spec
standing in for an uninstalled engine tests exactly what a real one would.
"""

import pytest

from ramabana.agent import Agent
from ramabana.core import Budget, ModelSpec, TOOL_MAX_FLOOR, budget_for
from ramabana.testing import FullHost
from ramabana.tools import tools_for

SMALL = ModelSpec('gemma-e2b', 'litert', 'litert-community/x', 16_384)
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)

RESEARCH = {'web_search', 'read_url', 'research', 'memory_search', 'memory_read',
            'memory_tree', 'memory_topics', 'memory_forget'}


def mk(host, spec):
    "An agent whose turn model is `spec`, without resolving a name against installed engines."
    a = Agent(host, extensions=False, subagents=False)
    a.routing.spec = lambda job='turn', fallback=True: spec
    return a


@pytest.fixture
def host(): return FullHost(files={'a.py': 'def a(): pass\n'})


def names(a): return {getattr(t, '__name__', '') for t in a.tools}


def test_small_window_drops_research_tools(host):
    "The groups a 16k model cannot use even when the host has them."
    assert not (names(mk(host, SMALL)) & RESEARCH)


def test_large_window_keeps_everything(host):
    assert RESEARCH <= names(mk(host, BIG))


def test_small_window_does_not_inline_a_skill_body(host):
    """The 3k tokens that made a 16k window unusable. `read_skill` still reaches it, so this
    costs a call rather than a capability."""
    small, big = mk(host, SMALL), mk(host, BIG)
    assert '## exhash' in big.system_prompt()
    assert '## exhash' not in small.system_prompt()
    assert len(small.system_prompt()) < len(big.system_prompt())


def test_unreadable_window_gets_the_full_briefing(host):
    """Not knowing a model's size must not turn into a smaller agent -- `_cloud_ctx` already
    assumes 128k when fastllm's table fails it."""
    for spec in (None, ModelSpec('mystery', 'remote', 'x/y', 0)):
        assert budget_for(spec, 6000) == Budget(tool_max=6000, note='full briefing')
        assert RESEARCH <= names(mk(host, spec))


def test_unresolvable_turn_model_keeps_the_tools(host):
    "`spec('turn')` raises for an engine that is not installed; a tool list must survive that."
    a = Agent(host, extensions=False, subagents=False)
    def boom(job='turn', fallback=True): raise RuntimeError('litert runtime is unavailable')
    a.routing.spec = boom
    assert RESEARCH <= names(a)
    assert a.budget.inline


def test_clip_reaches_the_tools(host, tmp_path):
    """`Agent(tool_max_len=...)` was documented as threaded into `tools_for` and was not, so a
    small model's results were clipped at a frontier model's budget."""
    p = tmp_path/'big.txt'
    p.write_text('\n'.join(f'line {i} ' + 'x'*60 for i in range(600)))
    from ramabana.tools import LocalHost
    h = LocalHost([str(tmp_path)], web=False, index=False)
    view = lambda mx: next(t for t in tools_for(h, mx=mx) if t.__name__ == 'view_file')
    assert len(view(budget_for(SMALL, 6000).tool_max)('big.txt')) < len(view(6000)('big.txt'))


def test_changing_model_rebuilds_what_was_sized_to_the_old_one(host):
    "Both the tool list and the briefing are sized to the turn model, so both must be dropped."
    a = Agent(host, extensions=False, subagents=False)
    cur = {'spec': BIG}
    a.routing.spec = lambda job='turn', fallback=True: cur['spec']
    a.routing.set = lambda name, job='turn': cur.__setitem__('spec', SMALL) or SMALL
    before = len(a.tools)
    assert '## exhash' in a.system_prompt()
    a.set_model('gemma-e2b')
    assert len(a.tools) < before
    assert '## exhash' not in a.system_prompt()


def test_budget_is_reported(host):
    "A capability withheld by choice must be visible; the briefing only describes what was built."
    assert '16k window' in mk(host, SMALL).budget.note
    assert mk(host, BIG).budget.note == 'full briefing'


def test_drop_only_withholds_named_groups(host):
    "A group not named is untouched, and the editing core is never dropped."
    every = {getattr(t, '__name__', '') for t in tools_for(host, lambda: [])}
    kept = {getattr(t, '__name__', '') for t in tools_for(host, lambda: [], drop=('memory', 'web'))}
    assert every - kept == RESEARCH & every
    assert {'view_file', 'replace_text', 'edit_file', 'search_code', 'grep'} <= kept


def test_floor_holds_for_a_tiny_window():
    "A sixteenth of a very small window is not a usable file view."
    assert budget_for(ModelSpec('t', 'litert', 'x', 4096), 6000).tool_max == TOOL_MAX_FLOOR
