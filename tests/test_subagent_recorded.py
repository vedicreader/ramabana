"A named model's sub-agent on a real model, recorded in `chatcache/`: does sizing its tools for that model change what it can do?"
import os, tempfile
from types import SimpleNamespace
from pathlib import Path
import pytest
from ramabana.agent import Agent
from ramabana.core import KEY_ENVS, ModelSpec
from ramabana.setup import ENV_DEFAULT
from ramabana.testing import FakeBackend, FullHost, fake_agent, recorded

URL, FACT = 'https://example.test/release-note', 'MARIGOLD-7'
ASK = f'What is the release codename on {URL}? Read the page with your tools; do not guess. Answer with the codename.'
TINY = ModelSpec('tiny-sub', 'remote', 'openai/tiny-sub', 16_000)   # never called: only its budget is read, which drops memory and web
BIG = ModelSpec('big-sub', 'remote', 'openai/big-sub', 200_000)

@pytest.fixture
def replay(monkeypatch):
    "Recorded answers, no credential and no machine config in the key; `URAI_RECORD_CHAT=1` records a miss."
    for k in [k for k in os.environ if k.startswith(ENV_DEFAULT)]: monkeypatch.delenv(k)
    monkeypatch.setenv('RAMABANA_CONFIG', str(Path(tempfile.mkdtemp())/'config.toml'))
    for k in KEY_ENVS.values(): monkeypatch.setenv(k, os.environ.get(k) or 'recorded')
    # a sub-agent's briefing names its run's fresh `uuid4` key, so the key would differ on every run
    import uuid, ramabana.runtime as rr
    monkeypatch.setattr(rr, 'uuid', SimpleNamespace(uuid4=lambda: uuid.UUID(int=0)))
    with recorded(): yield

def _ask(old):
    "`delegate_search` to gpt-4.1-mini beside a 16k default sub-agent model; `old` sizes its tools for the default, as before 0.2.67."
    root = Path(tempfile.gettempdir())/'ramabana-recorded-subagent'   # a fixed root: tool descriptions are part of the key
    a = Agent(FullHost(pages={URL: f'# Release note\n\nThe release codename is {FACT}.'}, root=root),
              model='gpt-4.1-mini', extensions=False, profile='full', drop_tools=())   # the recording holds the full tool list
    a.inbox_key = 'recorded'   # a fresh nonce per session; it is in the sub-agent's briefing, so in the key
    real_spec = a.spec_or_none
    a.spec_or_none = lambda job='turn': TINY if job == 'subagent' else real_spec(job)
    if old:
        real = a._sub_tools
        a._sub_tools = lambda depth=0, spec=None: real(depth)
    tools = {t.__name__ for t in a._sub_tools(spec=a._sub_backend('gpt-4.1-mini')[0].spec)}
    out = {t.__name__: t for t in a.tools}['delegate_search']([ASK], model='gpt-4.1-mini')
    return tools, out

def test_a_named_large_model_can_read_the_web_when_its_tools_are_sized_for_it(replay):
    "The default 16k model's list has no web tools, so a named gpt-4.1-mini given that list could not read the page."
    old_tools, old = _ask(old=True)
    new_tools, new = _ask(old=False)
    assert 'read_url' not in old_tools and 'read_url' in new_tools, (old_tools, new_tools)
    assert not old.startswith('ERROR') and FACT not in old, old
    assert FACT in new, new

def test_a_nested_delegation_caps_answers_at_its_own_models_size(tmp_path):
    "A sub-agent's own `delegate_search` cut answers to the default sub-agent model's size, not the size its own model reads."
    a, _ = fake_agent(FullHost(), cfg=tmp_path)
    small, big = a._sub_budget(), a._sub_budget(BIG)
    assert small.tool_max < big.tool_max, (small.tool_max, big.tool_max)
    class Long(FakeBackend):
        def spawn(self, sp='', tools=(), **kw):
            s = FakeBackend(self.spec, replies=['x' * (small.tool_max + 2000)], sp=sp, tools=tools, shared=True, **kw)
            self.spawned.append(s); return s
    sub = Long(BIG)
    a._sub_backend = lambda model='', effort='': (sub, {}, '')
    nest = {t.__name__: t for t in a._sub_tools(spec=BIG)}['delegate_search']
    assert len(nest(['q'])) > small.tool_max
