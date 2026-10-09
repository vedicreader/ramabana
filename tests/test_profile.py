"""The small-model profile: a local or small-window model gets fourteen tools and a one-screen briefing.

Thirty-six schemas and a five-thousand-token briefing confuse a 4B model; `auto` notices such a
model from its spec and briefs it small. `full` is byte-identical to what 0.2.2 sent. Nothing here loads a model.
"""
import pytest

from ramabana.agent import GIT_SHELL, Agent, git_shell_denial
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


# -- warm start ---------------------------------------------------------------------------

def test_every_profile_starts_cold_unless_asked(tmp_path):
    "`warm=None` resolves to off whatever the profile; `--warm` seeds the small profile as well as the full one."
    pytest.importorskip('dhrona')
    a, be = fake_agent(cfg=tmp_path, replies=['ok'], profile='auto')
    a.routing.spec = lambda job='turn', fallback=True: LOCAL
    assert a.profile == 'small' and a.warm is False and a.warm_choice is None
    a.ask('hello')
    assert len(be.hist_) == 2 and a.warm_report['used'] == []
    full, _ = fake_agent(cfg=tmp_path, replies=['ok'])
    assert full.warm is False and fake_agent(warm=True)[0].warm is True and fake_agent(warm=False)[0].warm is False and fake_agent(profile='small', warm=True)[0].warm is True


# -- fix round 1 ----------------------------------------------------------------------------

def test_the_small_briefings_git_claim_matches_what_run_shell_refuses(host):
    "Only `git_commit` is offered, so `git_shell_denial` refuses only `git commit`; the rule must not promise more."
    sp = mk(host, LOCAL).system_prompt()
    assert 'refuses `git commit`' in sp and 'push' not in sp and 'checkout' not in sp and 'stash' not in sp
    for sub, tool in GIT_SHELL.items():
        refused = bool(git_shell_denial(f'git {sub} x', tools=set(SMALL_TOOLS)))
        assert refused == (tool in SMALL_TOOLS), (sub, tool)
    assert git_shell_denial('git commit -m x', tools=set(SMALL_TOOLS)) and not git_shell_denial('git push', tools=set(SMALL_TOOLS))
