"`only_tools` names the only tools the model is offered, at the root, in its sub-agents and in a schema `ask`; None offers every tool and [] none."
import pytest

from ramabana.agent import Agent
from ramabana.core import ModelSpec
from ramabana.runtime import RishiBackend, use_chat
from ramabana.testing import FakeBackend, MemHost, fake_agent

CLAUDE = ModelSpec('cl', 'claude', 'claude-sonnet-5', 200_000)
HAIKU = ModelSpec('hk', 'claude', 'claude-haiku-5', 200_000)
OPUS = ModelSpec('op', 'claude', 'claude-opus-5', 200_000)
SONNET = ModelSpec('s4', 'claude', 'claude-sonnet-4-5', 200_000)


def names(tools): return {t.__name__ for t in tools}

def gather(query:str, # what to look for
           ):
    "Find a passage about `query`."
    return 'a passage'

def other(): "A tool nobody named."


def test_only_tools_offers_the_named_tools_everywhere_and_refuses_the_rest(monkeypatch):
    a, _ = fake_agent(only_tools=['gather', 'view_file', 'delegate_search'])
    a.add_tool(gather)   # named before it existed
    assert names(a.tools) == {'gather', 'view_file', 'delegate_search'}, names(a.tools)
    assert names(a._sub_tools()) == {'gather', 'view_file', 'delegate_search'}, 'a sub-agent regained a tool'
    with pytest.raises(ValueError, match="'other' is not in only_tools"): a.add_tool(other)
    assert 'other' not in names(a.registry.tools)
    small, _ = fake_agent(only_tools=['gather'], profile='small')
    small.add_tool(gather)
    assert names(small.tools) == {'gather'}, 'the small profile dropped a named tool'
    monkeypatch.setattr(Agent, '_quiet', property(lambda self: True))
    assert fake_agent(only_tools=[])[0].tools == [], 'the status tool came back'
    every = names(fake_agent()[0].tools)
    assert {'status', 'view_file', 'delegate_search', 'set_plan'} <= every


class Submitting(FakeBackend):
    "A model that hands back 42 through `submit_result`, then replies."
    def __init__(self, owner, **kw):
        super().__init__(**kw)
        self.owner = owner
    def _send(self, msg, **kw):
        self.sent.append(msg)
        next(t for t in self.owner.tools if t.__name__ == 'submit_result')(result=42)
        return 'handed back'

def test_a_schema_ask_needs_submit_result_named_and_then_returns_the_value():
    a, be = fake_agent(only_tools=[])
    with pytest.raises(ValueError, match="add 'submit_result' to `only_tools`"): a.ask('how many?', schema=int)
    assert be.sent == [] and a.history == [], 'the model was called'
    a, _ = fake_agent(only_tools=['submit_result'])
    be = Submitting(a); a._be = a._be_or_none = lambda job='turn': be
    r = a.ask('how many?', schema=int, strict=True)
    assert r.state == 'complete' and r.result == 42, r
    assert a.tools == [], 'the result tool outlived its ask'


def test_a_result_ask_without_a_schema_needs_no_submit_result_and_a_bare_name_is_refused():
    a, _ = fake_agent(only_tools=[], replies=['four'])
    r = a.ask('how many?', result=True)
    assert r.state == 'complete' and r.reply == 'four', r
    with pytest.raises(ValueError, match='only_tools'): fake_agent(only_tools='view_file')


class Capture:
    "A rishi chat stand-in that keeps the options it was built with."
    made = []
    def __init__(self, model_id, **kw):
        self.kw, self.hist = kw, []
        Capture.made.append(self)
    def __call__(self, msg, stream=False, **kw): return {'role': 'assistant', 'content': 'done'}
    def close(self): pass
    def reconfigure(self, sp=None, tools=None): pass

def claude_agent(**kw):
    a = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), extensions=False, profile='full', **kw)
    a.routing.turn, a.routing.policy = CLAUDE.name, {}
    for spec in (CLAUDE, HAIKU, OPUS, SONNET): a.routing._cache[spec.name] = spec
    return a

def test_warm_backend_starts_a_route_without_a_prompt_or_a_cost():
    a, be = fake_agent()
    assert a.warm_backend() is be and a.warm_backend('summary') is be
    assert be.sent == [] and a.use.total == 0 and a.use.cost == 0 and a.history == [], 'warming sent a prompt'
    assert a.warm is False, 'the warm-start property was replaced'
    a._be_or_none = lambda job='turn': None
    assert a.warm_backend('turn') is None


def test_a_spawned_child_keeps_a_strict_allowlist_whoever_spawns_it():
    be = RishiBackend(CLAUDE, claude_tools=[])
    Capture.made.clear()
    with use_chat(Capture):
        be.start()
        be.spawn(sp='monitor', tools=[]).start()
        assert Capture.made[-1].kw['claude_tools'] == [], 'a child that no `only_tools` route spawned got Claude Code defaults'
        be.spawn(sp='x', tools=[], claude_tools=['Read']).start()
        assert Capture.made[-1].kw['claude_tools'] == ['Read'], 'an explicit option lost to the inherited one'
        plain = RishiBackend(CLAUDE); plain.start(); plain.spawn(sp='x', tools=[]).start()
        assert 'claude_tools' not in Capture.made[-1].kw


def test_only_tools_reaches_every_claude_route_the_agent_builds(monkeypatch):
    monkeypatch.setattr('ramabana.agent.missing_runtime', lambda s: '')
    Capture.made.clear()
    with use_chat(Capture):
        a = claude_agent(only_tools=['view_file'])
        a.routing.policy['oneshot'] = HAIKU.name
        assert a._be('oneshot').start() is not None and Capture.made[-1].kw['claude_tools'] == [], 'a one-shot route got Claude Code defaults'
        assert a._named_backend(OPUS.name).chat.kw['claude_tools'] == [], 'a named sub-agent model got Claude Code defaults'
        assert a._cloud_backend_or_none(SONNET.name).chat.kw['claude_tools'] == [], 'a fan-out model got Claude Code defaults'
        a = claude_agent()
        assert 'claude_tools' not in a._be('oneshot').kw and 'claude_tools' not in a._named_backend(OPUS.name).kw


def test_a_strict_allowlist_drops_every_configured_grant_and_the_real_sdk_options_hold_none(tmp_path):
    pytest.importorskip('claude_agent_sdk')
    from rishi.claude import ClaudeChat
    grants = {'claude_server_tools': ['WebSearch'], 'mcp_servers': {'x': {'command': 'x'}}, 'mcp_tools': ['x'], 'allowed_tools': ['Bash'],
              'opts': {'allowed_tools': ['Bash'], 'tools': ['Bash'], 'mcp_servers': {'y': {'command': 'y'}}}}
    spec = ModelSpec('cl', 'claude', 'claude-sonnet-5', 200_000, opts=grants)
    loose = ClaudeChat('claude-sonnet-5', tools=[], workspace=tmp_path, **RishiBackend(spec)._runtime_kw())._opts('')
    assert loose.tools == ['WebSearch'] or 'Bash' in (loose.allowed_tools or []), 'the configured grants never reached the SDK, so this test proves nothing'
    strict = RishiBackend(spec, claude_tools=[])._runtime_kw()
    assert not {'claude_server_tools', 'mcp_servers', 'mcp_tools', 'allowed_tools'} & set(strict) and strict['claude_tools'] == [] and 'allowed_tools' not in strict['opts'], strict
    held = ClaudeChat('claude-sonnet-5', tools=[], workspace=tmp_path, **strict)._opts('')
    assert held.allowed_tools == [] and not held.mcp_servers, (held.allowed_tools, held.mcp_servers)
    if hasattr(ClaudeChat, 'oneshot_deadline_ok'):   # rishi 0.1.62 sends `--tools ''` for an empty allowlist; before it the SDK keeps Claude Code's default tools
        assert held.tools == [], held.tools


def test_only_tools_keeps_claude_codes_own_tools_off_the_root_and_its_children(monkeypatch):
    monkeypatch.setattr('ramabana.agent.missing_runtime', lambda s: '')
    agent = claude_agent
    Capture.made.clear()
    with use_chat(Capture):
        a = agent(only_tools=[])
        assert a.ask('hi') == 'done' and Capture.made[-1].kw['claude_tools'] == [], 'with no tools offered, Claude Code brings its default set'
        b, kw, _ = a._sub_backend()
        assert kw == {'claude_tools': []}, kw
        child = b.spawn(sp='sub', tools=[], **kw)
        child.start()
        assert Capture.made[-1].kw['claude_tools'] == [], 'the child ran with Claude Code tools'
        a = agent(only_tools=['view_file'])
        a.ask('hi')
        assert Capture.made[-1].kw['claude_tools'] == []
        a = agent()
        a.ask('hi')
        assert 'claude_tools' not in Capture.made[-1].kw and a._sub_backend()[1] == {}, 'an agent with every tool left Claude Code alone'
