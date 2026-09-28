"""The small-model profile: a local or small-window model gets fourteen tools and a one-screen briefing.

Thirty-six schemas and a five-thousand-token briefing confuse a 4B model; `auto` notices such a
model from its spec and briefs it small. `full` is byte-identical to what 0.2.2 sent. Nothing here loads a model.
"""
import inspect
import json

import pytest

from ramabana.agent import WARM_SMALL_CHARS, Agent
from ramabana.core import PROFILES, SMALL_PROFILE_CTX, SMALL_TOOLS, ModelSpec, profile_for
from ramabana.testing import FullHost, fake_agent

LOCAL = ModelSpec('gemma-e4b', 'litert', 'litert-community/gemma-4-E4B-it-litert-lm', 16_384)
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)
MID = ModelSpec('cloud-32k', 'remote', 'x/y-32k', SMALL_PROFILE_CTX)


def mk(host, spec, **kw):
    "An agent whose turn model is `spec`, without resolving a name against installed engines."
    a = Agent(host, extensions=False, **{'subagents': True, **kw})
    a.routing.spec = lambda job='turn', fallback=True: spec
    return a


def names(a): return {getattr(t, '__name__', '') for t in a.tools}


@pytest.fixture
def host(): return FullHost(files={'a.py': 'def a(): pass\n'})


# -- which profile ----------------------------------------------------------------------

def test_auto_resolves_from_the_turn_model():
    assert PROFILES == ('auto', 'small', 'full')
    assert profile_for(LOCAL) == 'small'                       # a local runtime, whatever its window
    assert profile_for(BIG) == 'full'                          # a cloud model with room
    assert profile_for(MID) == 'small'                         # a cloud model at the 32k line
    assert profile_for(None) == 'full' and profile_for(ModelSpec('m', 'remote', 'x/y', 0)) == 'full'   # unknown is not small
    assert profile_for(LOCAL, 'full') == 'full' and profile_for(BIG, 'small') == 'small'             # the flag wins
    with pytest.raises(ValueError): profile_for(BIG, 'tiny')
    with pytest.raises(ValueError): Agent(FullHost(), extensions=False, profile='tiny')


def test_the_agent_recomputes_the_profile_when_the_model_changes(host):
    a = mk(host, BIG)
    assert a.profile == 'full'
    cur = {'spec': BIG}
    a.routing.spec = lambda job='turn', fallback=True: cur['spec']
    a.routing.set = lambda name, job='turn': cur.__setitem__('spec', LOCAL) or LOCAL
    before = len(a.tools)
    note = a.set_model('gemma-e4b')
    assert a.profile == 'small' and len(a.tools) == len(SMALL_TOOLS) < before
    assert a.status()['profile'] == 'small' and 'small profile' in a.note
    assert 'small profile' in a.command('/model')            # the user can see which profile is active
    assert mk(host, LOCAL, profile='full').profile == 'full'


def test_the_fake_agent_stays_on_the_full_path():
    "The fake `SPEC` is a 1k window on a runtime nobody hosts; the rest of the suite tests the full path through it."
    a, _ = fake_agent()
    assert a.profile == 'full' and fake_agent(profile='auto')[0].profile == 'small'


# -- what a small agent is given --------------------------------------------------------

def test_the_small_catalog_is_exactly_the_list(host):
    "Given a host offering everything, the small profile offers the fourteen and nothing else: no delegation, no plan, no memory."
    everything = names(mk(host, BIG))
    assert set(SMALL_TOOLS) < everything and len(everything) > 30
    assert names(mk(host, LOCAL)) == set(SMALL_TOOLS)
    assert names(mk(host, BIG, profile='small')) == set(SMALL_TOOLS)
    assert names(mk(host, LOCAL, optin=('exhash',))) == set(SMALL_TOOLS) | {'edit_file'}   # an explicit opt-in still adds its tools
    assert names(mk(host, LOCAL, subagents=True, subagent_writes=True)).isdisjoint({'delegate_search', 'delegate_async', 'set_plan'})


def test_the_small_briefing_is_short_and_names_only_what_is_offered(host):
    a = mk(host, LOCAL)
    sp, full = a.system_prompt(), mk(host, BIG).system_prompt()
    assert len(sp) <= 4000 < len(full)
    for t in names(mk(host, BIG)) - set(SMALL_TOOLS):
        assert t not in sp, t
    for t in ('view_file', 'replace_text', 'search_code', 'grep', 'run_shell', 'run_python', 'git_status', 'notebook_cells'): assert f'`{t}`' in sp, t
    assert '## Skills' not in sp and 'Working as Claude' not in sp and 'Current plan' not in sp and 'Remembered' not in sp
    assert str(host.roots[0]) in sp and 'approval' in sp
    # the full profile with a small-window model is still the frugal briefing 0.2.2 sent
    frugal = mk(host, LOCAL, profile='full')
    assert 'memory_search' not in names(frugal) and 'delegate_search' in names(frugal) and len(frugal.system_prompt()) > 4000


def test_a_small_agent_gets_the_briefing_when_the_full_one_would_carry_a_plan(host, tmp_path):
    a = mk(host, LOCAL, cfg=tmp_path)
    a.plan.title = 'a plan'
    assert a.plan and 'Current plan' not in a.system_prompt()


# -- warm start ---------------------------------------------------------------------------

def test_a_small_profile_is_seeded_with_one_round_even_on_a_small_window(tmp_path):
    pytest.importorskip('dhrona')
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='auto')
    a.routing.spec = lambda job='turn', fallback=True: LOCAL
    assert a.profile == 'small' and not a.budget.inline     # the gate that keeps seeds from a 16k window
    a.ask('hello')
    used = a.warm_report['used']
    assert len(used) == 1 and used[0]['name'] == 'search-choice'   # best-ranked round that binds to the fourteen
    seeded = be.hist_[:-2]
    calls = {tc['function']['name'] if 'function' in tc else tc['name'] for m in seeded for tc in m.get('tool_calls') or []}
    assert calls and calls <= set(SMALL_TOOLS) and len(json.dumps(seeded)) < WARM_SMALL_CHARS
    assert any(r['name'] == 'git-flow' for r in a.warm_report['skipped'])


def test_an_oversized_round_is_skipped_with_the_reason(tmp_path, monkeypatch):
    pytest.importorskip('dhrona')
    from ramabana import agent as agent_mod
    monkeypatch.setattr(agent_mod, 'WARM_SMALL_CHARS', 100)
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='small')
    a.ask('hello')
    assert a.warm_report['used'] == [] and len(be.hist_) == 2
    assert any('100' in r['reason'] and r['name'] == 'search-choice' for r in a.warm_report['skipped'])


# -- the CLI ----------------------------------------------------------------------------------

def test_the_cli_carries_the_flag(tmp_path):
    from ramabana import cli
    assert inspect.signature(cli.main).parameters['profile'].default == 'auto'
    a, _ = cli.mk_agent([str(tmp_path)], approve='none', web=False, warm=False, profile='small', host_kw=dict(index=False))
    assert a.profile == 'small' and names(a) <= set(SMALL_TOOLS)
