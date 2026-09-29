"""The small-model profile: a local or small-window model gets fourteen tools and a one-screen briefing.

Thirty-six schemas and a five-thousand-token briefing confuse a 4B model; `auto` notices such a
model from its spec and briefs it small. `full` is byte-identical to what 0.2.2 sent. Nothing here loads a model.
"""
import inspect
import json

import pytest

from ramabana.agent import GIT_SHELL, WARM_SMALL_CHARS, Agent, git_shell_denial
from ramabana.core import PROFILES, SMALL_PROFILE_CTX, SMALL_TOOLS, ModelSpec, profile_for
from ramabana.testing import FullHost, fake_agent
from ramabana.tools import small_tool

LOCAL = ModelSpec('gemma-e4b', 'litert', 'litert-community/gemma-4-E4B-it-litert-lm', 16_384)
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)
MID = ModelSpec('cloud-32k', 'remote', 'x/y-32k', SMALL_PROFILE_CTX)


def mk(host, spec, **kw):
    "An agent whose turn model is `spec`, without resolving a name against installed engines."
    a = Agent(host, extensions=False, **{'subagents': True, **kw})
    a.routing.spec = lambda job='turn', fallback=True: spec
    return a


def names(a):
    "The catalog's tool names; a LiteRT agent's display-only `status` tool is not in the catalog."
    return {getattr(t, '__name__', '') for t in a.tools} - {'status'}


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
    assert a.profile == 'small' and len(names(a)) == len(SMALL_TOOLS) < before
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

def test_a_small_profile_starts_cold_unless_asked(tmp_path):
    "A small model copies an example's paths literally, so `warm=None` resolves to off for the small profile and on for the full one."
    pytest.importorskip('dhrona')
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='auto')
    a.routing.spec = lambda job='turn', fallback=True: LOCAL
    assert a.profile == 'small' and a.warm is False and a.warm_choice is None
    a.ask('hello')
    assert len(be.hist_) == 2 and a.warm_report['used'] == [] and 'small profile' in a.warm_report['note']
    assert any('warm start off (small profile)' in n and '--warm' in n for n in a.host.notes) if hasattr(a.host, 'notes') else True
    full, _ = fake_agent(cfg=tmp_path, replies=['ok'])
    assert full.warm is True and fake_agent(warm=False)[0].warm is False and fake_agent(profile='small', warm=True)[0].warm is True


def test_a_small_profile_asked_to_warm_gets_one_round_even_on_a_small_window(tmp_path):
    pytest.importorskip('dhrona')
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='auto', warm=True)
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
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='small', warm=True)
    a.ask('hello')
    assert a.warm_report['used'] == [] and len(be.hist_) == 2
    assert any('100' in r['reason'] and r['name'] == 'search-choice' for r in a.warm_report['skipped'])


# -- the CLI ----------------------------------------------------------------------------------

def test_the_cli_carries_the_flag(tmp_path):
    from ramabana import cli
    ps = inspect.signature(cli.main).parameters
    assert ps['profile'].default == 'auto' and ps['warm'].default is False and ps['no_warm'].default is False   # --warm / --no-warm; neither = auto
    assert cli.main.__wrapped__('hi', warm=True, no_warm=True, root=str(tmp_path)) == 2   # the flags contradict
    a, _ = cli.mk_agent([str(tmp_path)], approve='none', web=False, warm=False, profile='small', host_kw=dict(index=False))
    assert a.profile == 'small' and names(a) <= set(SMALL_TOOLS)


# -- fix round 1 ----------------------------------------------------------------------------

def test_the_small_briefings_git_claim_matches_what_run_shell_refuses(host):
    "Only `git_commit` is offered, so `git_shell_denial` refuses only `git commit`; the rule must not promise more."
    sp = mk(host, LOCAL).system_prompt()
    assert 'refuses `git commit`' in sp and 'push' not in sp and 'checkout' not in sp and 'stash' not in sp
    for sub, tool in GIT_SHELL.items():
        refused = bool(git_shell_denial(f'git {sub} x', tools=set(SMALL_TOOLS)))
        assert refused == (tool in SMALL_TOOLS), (sub, tool)
    assert git_shell_denial('git commit -m x', tools=set(SMALL_TOOLS)) and not git_shell_denial('git push', tools=set(SMALL_TOOLS))


def test_a_registry_tool_marked_small_reaches_the_small_catalog(host):
    "An embedder's own tools (a steering refusal, a canvas) stay reachable when they say so; the rest stay out; the full catalog is unchanged."
    @small_tool
    def user_steering(reason: str) -> str:
        "Refuse and say why."
        return reason
    def canvas_show(path: str) -> str:
        "Show a canvas."
        return path
    assert user_steering.small is True and not getattr(canvas_show, 'small', False)
    a = mk(host, LOCAL); a.registry.tool(user_steering); a.registry.tool(canvas_show)
    assert names(a) == set(SMALL_TOOLS) | {'user_steering'}
    b = mk(host, BIG); b.registry.tool(user_steering); b.registry.tool(canvas_show)
    assert {'user_steering', 'canvas_show'} <= names(b) and len(names(b)) == len(names(mk(host, BIG))) + 2


def test_optin_names_are_checked_at_construction(host):
    with pytest.raises(ValueError, match='nope'): Agent(host, extensions=False, optin=('nope',))
    with pytest.raises(ValueError, match='exhash'): Agent(host, extensions=False, optin='nope')
    assert mk(host, LOCAL, optin='exhash').optin == ('exhash',)


def test_auto_small_says_so_once_at_start_up(host):
    "The start-up line names the model and the reason, so a short tool list is not a mystery. Once; never when the profile was asked for."
    from ramabana.testing import FakeBackend
    def agent(**kw):
        a, be = fake_agent(host, replies=['ok'], **kw)
        a.routing.spec = lambda job='turn', fallback=True: LOCAL
        be.spec = LOCAL
        return a
    a = agent(profile='auto'); a.start(); a.start()
    lines = [n for n in host.notes if n.startswith('small profile:')]
    assert len(lines) == 1 and 'gemma-e4b is local' in lines[0] and 'warm start off' in lines[0] and '--profile full' in lines[0]
    assert '15 tools' in lines[0], 'the fourteen and `status`'
    host.notes.clear()
    b = agent(); b.start()
    assert not [n for n in host.notes if n.startswith('small profile:')]                 # full says nothing
    c = agent(profile='small'); c.start()
    assert not [n for n in c.host.notes if n.startswith('small profile:')]                 # asked for explicitly: nothing to explain
