"""Briefing contracts: budget, tool channel, skill disclosure, and a local-window e2e fit.

Budget arithmetic lives in `00_core.ipynb`. Compaction under a full briefing is in `test_context.py`.
Nothing here loads a model.
"""

import pytest

from ramabana import runtime
from ramabana import agent as A
from ramabana.agent import Agent
from ramabana.core import ModelSpec, forget_forced_tags, tool_channel
from ramabana.runtime import estimate_tokens, threshold
from ramabana.testing import FullHost, ScriptedBackend, Step, fake_agent
from ramabana.tools import LocalHost, Skill, clip_lines, tools_for

SMALL = ModelSpec('gemma-e2b', 'litert', 'litert-community/x', 16_384)   # the local default
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)
#: Claude Code itself, through `rishi.claude`.
CLAUDE = ModelSpec('claude/claude-sonnet-5', 'claude', 'claude-sonnet-5', 128_000)


#: Stands in for the `exhash` body the briefing inlines: ~3k tokens, which is what made a 16k
#: window unusable. A literal keeps the test independent of which skills are installed.

BIG_SKILL = Skill(name='exhash', source='test', description='hash-verified edits',
                  where='test', _text='EXHASH BODY. ' + 'edit like this. ' * 800)


def mk(host, spec, **kw):
    "An agent whose turn model is `spec`, without resolving a name against installed engines."
    a = Agent(host, extensions=False, **{'subagents': False, **kw})
    a.routing.spec = lambda job='turn', fallback=True: spec
    a._skills = [BIG_SKILL]
    return a


@pytest.fixture
def host(): return FullHost(files={'a.py': 'def a(): pass\n'})


def names(a): return {getattr(t, '__name__', '') for t in a.tools}


# -- what the budget decides -----------------------------------------------------------

def test_one_long_line_does_not_escape_the_clip():
    """A minified bundle, a one-line JSON document or a wide CSV row is a single line, and
    `clip_lines` returned the first one whole so a result was never empty -- ten thousand tokens,
    which was the entire working room of a 16k model spent on one call."""
    out = clip_lines(['x' * 40_000], n=4096)
    assert len(out) < 4200 and 'chars' in out and '40000' in out   # chars: no line to resume from
    # A long line reached after short ones is still reported by line, so the resume hint works.
    out2 = clip_lines(['short', 'y' * 40_000], n=4096, more='call again from {next}')
    assert 'more line(s) not shown' in out2 and 'call again from 2' in out2
    assert clip_lines(['a', 'b'], n=4096) == 'a\nb'                # and short lines are untouched


# -- what a sub-agent is given ---------------------------------------------------------

@pytest.mark.parametrize('turn,sub', [(BIG, BIG), (BIG, SMALL), (SMALL, SMALL), (SMALL, BIG)],
                         ids=['cloud-same', 'cloud-local', 'local-same', 'local-cloud'])
@pytest.mark.parametrize('writes', [False, True], ids=['read', 'write'])
def test_a_sub_agent_never_gets_the_roots_delegation_watch_or_plan_tools(host, turn, sub, writes):
    """A cloud turn whose sub-agents afford the same budget handed them `self.tools` whole, so a
    sub-agent could delegate, watch and rewrite the root's plan. Every path, and the monitors'
    reviewer, takes `_sub_plain`; the root keeps its own tools."""
    host.without = frozenset({'ask', 'api'})   # the watches too
    a = mk(host, turn, subagents=True, subagent_writes=writes, profile='full')
    a.routing.spec = lambda job='turn', fallback=True: turn if job == 'turn' else sub
    assert A.ROOT_ONLY <= names(a), 'the root keeps delegation, watches and the plan'
    for tools in (a._sub_plain(), a._sub_tools(), a.monitors.get_tools()):
        got = {getattr(t, '__name__', '') for t in tools}
        assert not (got & A.ROOT_ONLY)
        if writes: assert {'replace_text', 'run_python'} <= got, 'a writing sub-agent keeps the writes'


# -- where the tool schemas travel -----------------------------------------------------

def test_a_refused_wire_channel_is_learned_once_and_the_turn_still_answers(monkeypatch):
    """The case detection cannot reach. A policy at a path the three-path probe does not know is
    only ever learned from the failure it causes, and an agent that has to be told by hand is one
    that sat there with no tools until somebody read the source. One turn pays for the lesson."""
    calls = []

    class Refusing(runtime.RishiBackend):
        def _start(self): return object()          # nothing is sent; `_send` is the whole wire
        def _usage(self): return None
        def _send(self, msg, **kw):
            calls.append(tool_channel(self.spec))
            if calls[-1] == 'native': raise RuntimeError('mcp_servers disallowed by policy')
            return 'answered'

    b = Refusing(BIG, tools=[lambda: None])
    try:
        assert b.send('hi') == 'answered'
        assert calls == ['native', 'tags']         # tried the wire, learned, and finished the turn
        assert any('travel in the system prompt' in p for p in b.problems)
        assert tool_channel(BIG) == 'tags'         # and the next turn does not try the wire again
    finally: forget_forced_tags()


def test_a_tag_call_that_came_back_as_prose_is_reported(monkeypatch):
    """What the tags channel costs. On the wire a malformed call raises; in the prompt it is just
    text, and it reads to the user as the model discussing a call it never made. Both paths are
    checked, because the CLI streams and only `ask` sends."""
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')

    class Tagged(runtime.RishiBackend):
        def _start(self): return self
        def _send(self, msg, **kw): return '<tool_call>{"name": "view_file"'
        def _stream(self, msg, **kw): yield '<tool_call>{"name": '; yield '"view_file"'
        def _usage(self): return runtime.Usage(model=self.spec.model_id)

    class Clean(Tagged):
        def _send(self, msg, **kw): return 'the answer, with no tags in it'

    sent = Tagged(CLAUDE); sent.send('go')
    assert any('came back as prose' in p for p in sent.problems), sent.problems
    streamed = Tagged(CLAUDE); ''.join(streamed.stream('go'))
    assert any('came back as prose' in p for p in streamed.problems), streamed.problems
    clean = Clean(CLAUDE); clean.send('go')
    assert not clean.problems

    # ...and the shape with no tags at all. haiku writes the call object and then invents the
    # result after it, which rishi's parser must refuse, so the reply reached the user as raw JSON
    # with nothing reported and no corrective turn: the detector only looked for `<tool_call`.
    def _tool(pattern): return pattern            # a name the backend really carries
    _tool.__name__ = 'grep'

    class Bare(Tagged):
        def _send(self, msg, **kw):
            return '{"name": "grep", "arguments": {"pattern": "x"}}  Tool result (grep): 3 matches'

    bare = Bare(CLAUDE, tools=[_tool]); bare.send('go')
    # ...and the report names the shape it saw, since the tags it mentions were never there
    assert any('bare JSON' in p for p in bare.problems), bare.problems
    assert not any('came back as prose' in p for p in bare.problems), bare.problems
    assert any('came back as prose' in p for p in sent.problems)   # the tagged shape still reads so
    # a reply naming something this backend does not carry is prose about JSON, not a lost call
    assert not Bare(CLAUDE, tools=[])._needs_tag_retry('{"name": "grep", "arguments": {"pat": "x"}}')
    assert not Bare(CLAUDE, tools=[_tool])._needs_tag_retry('grep takes a "name" and a pattern')


# -- the property all of it exists for -------------------------------------------------

def test_a_local_turn_fits_its_window_end_to_end(tmp_path):
    "Four-call frugal turn on the 16k local model fits under the compaction threshold."
    (tmp_path/'big.py').write_text('\n'.join(f'def f{i}(): return {i}  # ' + 'x'*70
                                             for i in range(900)))
    host = LocalHost([str(tmp_path)], web=False, index=False)

    PASSES = [(1, 200), (200, 400), (400, 600), (600, 800)]

    def cost(inline, tool_max):
        """Everything one turn puts in front of the engine, whichever channel the schemas take:
        the briefing, the schemas, and what four real `view_file` results actually come back as.
        """
        import json
        from urai import mk_toolspec
        from ramabana.agent import system_prompt
        tools = tools_for(host, lambda: [BIG_SKILL], mx=tool_max)
        view = next(t for t in tools if getattr(t, '__name__', '') == 'view_file')
        return (estimate_tokens(system_prompt(host, [BIG_SKILL], inline, tools=tools))
                + estimate_tokens(json.dumps([mk_toolspec(t) for t in tools]))
                + sum(estimate_tokens(view('big.py', start=a, end=b)) for a, b in PASSES))

    # First: the turn really runs, through the real tools, on the real Agent.
    a = Agent(host, extensions=False, subagents=False)
    a.routing.spec = lambda job='turn', fallback=True: SMALL
    a._skills = [BIG_SKILL]
    steps = [Step(tool=('view_file', {'path': 'big.py', 'start': s, 'end': e})) for s, e in PASSES]
    be = ScriptedBackend(SMALL, steps=steps + [Step(text='All four read. Nothing to change.')],
                         token_delay=0, tools=a.tools)
    a._be = a._be_or_none = lambda job='turn': be
    answer = a.ask('read big.py in four passes and tell me if anything needs changing')
    assert 'All four read' in answer
    assert [t for t, _ in a.calls] == ['view_file'] * 4
    assert not a.budget.inline and a.budget.tool_max < 6000      # it really is the frugal budget

    # Then: what that turn costs now, against what it cost before. The Agent cannot be made to
    # reproduce the old behaviour any more -- `budget` overrides `inline_skills`, which is the
    # fix -- so the old configuration is rebuilt from the same pieces it was assembled from.
    budget = threshold(SMALL.ctx)                                # where compaction fires: 12,288
    now = cost((), a.budget.tool_max)
    was = cost(('exhash',), 6000)
    assert was > budget, f'the old briefing fitted after all ({was} of {budget})'
    assert now < budget, f'{now} of {budget}'
    # The slack asserted here was 1500 while `estimate_tokens` assumed chars/4. It measures 3.25
    # now, which ornith and qwen3 bear out. The briefing did not change. Its price is what it
    # always was. The turn still fits, and still leaves a reply room inside the 16k window. What
    # it no longer has is much room before compaction fires. Most of that cost is the schemas
    # rather than the prose: 5,136 tokens against a 1,548-token briefing.
    assert budget - now > 500, f'only {budget - now} left before compaction fires'
    assert SMALL.ctx - now > 4000, f'only {SMALL.ctx - now} of window left to answer in'
    # A 200k model is untouched by any of it: the old cost was never its problem.
    assert was < threshold(BIG.ctx)


# -- what rides along with a prompt ----------------------------------------------------

def test_a_harness_is_held_to_its_own_window_not_the_tables():
    """`rishi.claude` used to carry no session state: each turn rendered the whole conversation to
    a text prompt and sent it again, so the ceiling was what was affordable to re-send rather than
    what the model held -- at the tables' 1M figure ramabana compacted at 983,616 tokens and
    re-sent that much per turn, which was the hang.

    Rishi resumes a Claude Code session now, so that reason has gone and the session's window is
    the honest number. Claude Code serves 200k under a model's plain id and 1M under `<id>[1m]`,
    so the 5-series is asked for by that name and held to 1M; anything else keeps what it is served.
    """
    from ramabana.core import DFLT_AGENT_CTX, claude_ctx, claude_wire, resolve
    for name in ('sonnet', 'opus', 'haiku', 'fable', 'claude/claude-opus-5-5'):
        assert resolve(name).ctx == 1_000_000, name
        assert claude_wire(resolve(name).model_id) == resolve(name).model_id + '[1m]', name
    assert claude_ctx('claude-opus-4-5') == 200_000 and claude_wire('claude-opus-4-5') == 'claude-opus-4-5'
    # a family whose window is not recorded here still gets the affordable ceiling
    assert claude_ctx('claude-unreleased-9') == DFLT_AGENT_CTX and claude_wire('claude-unreleased-9') == 'claude-unreleased-9'


def test_the_model_chooses_its_tools_unless_the_user_names_one():
    """A keyword router used to pick a route per turn and run its first tool up front: a pasted
    handoff mentioning "today" was web-searched whole. Current models choose well; only a tool the
    user names with `/tool` is put ahead of the turn."""
    for spec in (CLAUDE, ModelSpec('gpt', 'remote', 'gpt-5.6', 200_000)):
        a, be = fake_agent(replies=['done', 'done'])
        a.routing.spec = lambda job='turn', fallback=True, _s=spec: _s
        a.ask('what are the latest nbdev release notes? where is this repo configured?')
        sent = str(be.sent[-1])
        assert not any(x in sent for x in ('<tool-plan', '<preflight-tool', '<output-contract>')), spec.name
        a.ask('find it /grep threshold')
        assert '<tool-plan route="explicit">' in str(be.sent[-1])
