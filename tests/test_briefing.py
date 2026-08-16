"""Briefing contracts: budget, tool channel, skill disclosure, and a local-window e2e fit.

Budget arithmetic lives in `00_core.ipynb`. Compaction under a full briefing is in `test_context.py`.
Nothing here loads a model.
"""

import pytest

from ramabana import runtime
from ramabana import agent as A
from ramabana.agent import Agent
from ramabana.core import (SMALL_CTX, Budget, ModelSpec, budget_for, force_tags, forget_forced_tags,
                           tool_channel)
from ramabana.runtime import estimate_tokens, threshold
from ramabana.testing import FakeBackend, FullHost, ScriptedBackend, Step, fake_agent
from ramabana.tools import LocalHost, Skill, _delegate_result, clip_lines, named_skills, sub_sp, tools_for

SMALL = ModelSpec('gemma-e2b', 'litert', 'litert-community/x', 16_384)   # the local default
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)
CC = ModelSpec('cc', 'remote', 'claude_code/claude-sonnet-5', 200_000)
CURSOR = ModelSpec('opus5', 'cursor', 'claude-opus-5', 200_000)
#: The same model as `CC`, reached through Claude Code itself rather than FastLLM's transport.
CLAUDE = ModelSpec('claude/claude-sonnet-5', 'claude', 'claude-sonnet-5', 128_000)


def _claude_transport():
    """`_claude_payload_compat` applied to a stand-in transport; returns a fresh payload's options.

    A stand-in rather than FastLLM's: what is under test is the gate, and the real one needs the
    Claude Agent SDK installed and a login to build a payload at all.
    """
    from types import SimpleNamespace
    def mk_payload(*a, **kw):
        return {'prompt': '', 'options': SimpleNamespace(
            model=CC.model_id.split('/', 1)[1], mcp_servers={'ramabana': object()},
            allowed_tools=['mcp__ramabana__search_code'], strict_mcp_config=True)}
    t = SimpleNamespace(mk_payload=mk_payload)
    from ramabana.core import _claude_payload_compat
    _claude_payload_compat(t)
    return lambda: t.mk_payload()['options']

RESEARCH = {'web_search', 'read_url', 'research', 'memory_search', 'memory_read',
            'memory_tree', 'memory_topics', 'memory_forget'}

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

def test_a_frugal_agent_differs_from_a_full_one_in_every_way_the_budget_decides(host):
    "Small window: no research tools, no inlined skill body, smaller clip, shorter briefing."
    small, big = mk(host, SMALL), mk(host, BIG)
    assert not (names(small) & RESEARCH) and RESEARCH <= names(big)
    assert '## exhash' in big.system_prompt() and '## exhash' not in small.system_prompt()
    assert small.budget.tool_max < big.budget.tool_max
    assert '16k window' in small.budget.note and big.budget.note == 'full briefing'
    # And the whole point: the frugal briefing is dramatically smaller.
    assert estimate_tokens(small.system_prompt()) < estimate_tokens(big.system_prompt()) / 2


def test_a_window_we_could_not_read_is_not_a_small_window(host):
    """Not knowing a model's size must not turn into a smaller agent -- `_cloud_ctx` already
    assumes 128k when fastllm's table fails it. `spec('turn')` also raises outright for an engine
    that is not installed, and a host with no model still has a tool list."""
    for spec in (None, ModelSpec('mystery', 'remote', 'x/y', 0)):
        assert budget_for(spec, 6000) == Budget(tool_max=6000, note='full briefing')
        assert RESEARCH <= names(mk(host, spec))

    a = Agent(host, extensions=False, subagents=False)
    def boom(job='turn', fallback=True): raise RuntimeError('litert runtime is unavailable')
    a.routing.spec = boom
    assert RESEARCH <= names(a) and a.budget.inline


def test_the_clip_reaches_the_tools(tmp_path):
    """`Agent(tool_max_len=...)` was documented as threaded into `tools_for` and was not, so a
    small model's results were clipped at a frontier model's budget."""
    (tmp_path/'big.txt').write_text('\n'.join(f'line {i} ' + 'x'*60 for i in range(600)))
    h = LocalHost([str(tmp_path)], web=False, index=False)
    view = lambda mx: next(t for t in tools_for(h, mx=mx) if t.__name__ == 'view_file')
    assert len(view(budget_for(SMALL, 6000).tool_max)('big.txt')) < len(view(6000)('big.txt'))


def test_changing_model_rebuilds_what_was_sized_to_the_old_one(host):
    "Both the tool list and the briefing are sized to the turn model, so both must be dropped."
    a = mk(host, BIG)
    cur = {'spec': BIG}
    a.routing.spec = lambda job='turn', fallback=True: cur['spec']
    a.routing.set = lambda name, job='turn': cur.__setitem__('spec', SMALL) or SMALL
    before = len(a.tools)
    assert '## exhash' in a.system_prompt()
    a.set_model('gemma-e2b')
    assert len(a.tools) < before
    assert '## exhash' not in a.system_prompt()
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

def test_a_sub_agent_is_sized_to_the_model_sub_agents_run_on(host):
    """`DEFAULT_POLICY` points `subagent` at the small local model, so the default shape is a
    frontier turn delegating to a 16k engine, which was being handed the turn model's schemas at
    the turn model's clip. When both models can afford the same briefing the turn's own list is
    reused, since probing the host twice buys nothing."""
    a = mk(host, BIG, subagents=True)
    a.routing.spec = lambda job='turn', fallback=True: BIG if job == 'turn' else SMALL
    sub = {getattr(t, '__name__', '') for t in a._sub_plain()}
    assert not (sub & RESEARCH) and RESEARCH <= names(a)
    assert 'delegate_search' not in sub                  # a sub-agent does not delegate

    same = mk(host, BIG, subagents=True)
    same.tools
    assert same._sub_plain() is same._plain


def test_a_task_can_name_the_skills_it_needs():
    """The caller holds the skill index and the sub-agent does not, so naming a skill is how a
    one-job sub-agent starts holding it instead of spending a step on `read_skill`. A name that
    matched nothing is reported, because a sub-agent briefed without the skill its caller asked
    for answers from general knowledge and sounds exactly as confident as one that had it."""
    sk = [Skill(name='kosha', source='t', description='code answers', where='t', _text='ASK KOSHA'),
          Skill(name='cfeasy', source='t', description='deploys', where='t', _text='DEPLOY THIS WAY')]
    got, note = named_skills(lambda: sk, 'cfeasy')
    assert [s.name for s in got] == ['cfeasy'] and not note
    brief = sub_sp(skills=got)
    assert 'DEPLOY THIS WAY' in brief and 'ASK KOSHA' not in brief
    assert sub_sp() == sub_sp(skills=())                 # naming nothing changes nothing

    got, note = named_skills(lambda: sk, 'kosha, nosuchskill')
    assert [s.name for s in got] == ['kosha']
    assert 'nosuchskill' in note and 'kosha' in note


def test_named_skills_reach_the_sub_agents_briefing(host):
    "End to end: the tool the model calls puts the named body in the spawned conversation."
    a = mk(host, BIG, subagents=True)
    a._skills = [Skill(name='cfeasy', source='t', description='deploys', where='t',
                       _text='DEPLOY THIS WAY')]
    be = FakeBackend(BIG)
    be.start()
    a._be_or_none = lambda job='turn': be
    search = next(t for t in a.tools if getattr(t, '__name__', '') == 'delegate_search')
    assert 'sub answer' in search('how do we deploy?', skills='cfeasy')   # what `spawn` scripts
    assert 'DEPLOY THIS WAY' in be.spawned[0].sp
    assert 'nosuchskill' in search('how do we deploy?', skills='nosuchskill')


def test_delegated_output_rejects_empty_and_repetitive_prose():
    assert 'no answer' in _delegate_result('')
    assert 'repetitive output' in _delegate_result('Cmd+V ' * 20)
    assert _delegate_result('found tools.py:42') == 'found tools.py:42'


# -- where the tool schemas travel -----------------------------------------------------

def test_the_tool_channel_is_one_decision(monkeypatch):
    """`native` is the default and better wherever the wire is open. A refused channel is
    remembered per model so the lesson costs one turn rather than every turn, and the environment
    forces either for a machine broken in a way nothing here detects."""
    # `native` is the default *where the wire is open*, so say that rather than inheriting it:
    # this machine's own Claude Code config would otherwise decide the answer.
    import ramabana.core as _core
    monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: False)
    assert tool_channel(BIG) == 'native' and tool_channel(CC) == 'native'
    try:
        force_tags(CC.model_id, 'MCP refused by policy')
        assert tool_channel(CC) == 'tags'
        assert tool_channel(BIG) == 'native'             # per model, not a global switch
    finally:
        forget_forced_tags()
    assert tool_channel(CC) == 'native'                  # a fixed configuration is tried again

    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')
    assert tool_channel(BIG) == 'tags'
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'native')
    assert tool_channel(CC) == 'native'
    # The override reaches an agent harness too, which it did not before: it is the answer for a
    # machine broken in a way nothing here detects, and those machines run agent harnesses as well.
    assert tool_channel(CLAUDE) == 'native'
    monkeypatch.delenv('RAMABANA_TOOL_CHANNEL')

    # An agent harness answers for itself. Only its SDK can carry the schemas -- either CLI would
    # have to declare them through a config file a managed policy refuses -- so without one the
    # answer is tags, and the spec alone can only predict which path a chat will take.
    monkeypatch.setattr(_core, '_agent_native', lambda rt: False)
    assert tool_channel(CURSOR) == 'tags' and tool_channel(CLAUDE) == 'tags'
    monkeypatch.setattr(_core, '_agent_native', lambda rt: True)
    assert tool_channel(CURSOR) == 'native' and tool_channel(CLAUDE) == 'native'

    # ...and a live chat overrules the prediction, because it is the thing that knows. A Claude
    # chat that opened an MCP server and had it refused is on tags now; nothing about the spec says so.
    class _Chat:
        def __init__(self, ch): self.tool_channel = ch
    assert tool_channel(CLAUDE, _Chat('tags')) == 'tags'
    assert tool_channel(CURSOR, _Chat('native')) == 'native'
    assert tool_channel(CLAUDE, _Chat('nonsense')) == 'native'   # not a channel; the prediction stands
    assert tool_channel(CLAUDE, None) == 'native'


def test_the_claude_harness_is_the_way_in_a_managed_policy_leaves_open(monkeypatch):
    """Two ways to reach Claude, and only one of them an enterprise policy can close.

    `claude_code/...` goes through FastLLM's transport, which declares tools as an in-process MCP
    server -- the thing a managed configuration forbids. `claude/...` drives Claude Code itself and
    never opens one, so it is on the tags channel unconditionally rather than on discovery of a
    config file at one of three paths.
    """
    import ramabana.core as _core
    monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: False)
    assert tool_channel(CC) == 'native'        # the wire is open here, so the transport keeps it
    # ...and the harness has a channel of its own only where its SDK is installed to carry it
    monkeypatch.setattr(_core, '_agent_native', lambda rt: False)
    assert tool_channel(CLAUDE) == 'tags'

    assert CLAUDE.runtime == 'claude' and not CLAUDE.local   # the binary is local, the model is not
    assert CLAUDE.model_id == 'claude-sonnet-5'              # the `claude/` prefix is rishi's, not the id's


def test_the_claude_payload_is_stripped_for_every_reason_the_wire_is_shut(monkeypatch):
    """The other half of the tags decision, and the half that used to be missed.

    Moving the schemas into the prompt is not enough on its own: the in-process MCP server stays
    in the payload and a managed policy refuses it anyway. Gating the strip on the config probe
    alone meant the two ways of reaching tags that the probe cannot see -- the override that
    exists for a policy at an undocumented path, and a refusal already learned from a failure --
    moved the schemas and then failed exactly as they had before."""
    import ramabana.core as _core
    monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: False)
    mk = _claude_transport()
    assert mk().mcp_servers and mk().strict_mcp_config is True   # wire open: untouched

    for shut, undo in ((lambda: monkeypatch.setenv('RAMABANA_CLAUDE_TAG_TOOLS', '1'),
                        lambda: monkeypatch.delenv('RAMABANA_CLAUDE_TAG_TOOLS')),
                       (lambda: monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: True),
                        lambda: monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: False)),
                       (lambda: force_tags(CC.model_id, 'refused mid-turn'), forget_forced_tags)):
        shut()
        try:
            o = mk()
            assert o.mcp_servers == {} and o.allowed_tools == [] and o.strict_mcp_config is False
        finally: undo()


def test_a_refused_wire_channel_is_learned_once_and_the_turn_still_answers(monkeypatch):
    """The case detection cannot reach. A policy at a path the three-path probe does not know is
    only ever learned from the failure it causes, and an agent that has to be told by hand is one
    that sat there with no tools until somebody read the source. One turn pays for the lesson."""
    import ramabana.core as _core
    monkeypatch.setattr(_core, '_managed_claude_mcp', lambda: False)
    calls = []

    class Refusing(runtime.RishiBackend):
        def _start(self): return object()          # nothing is sent; `_send` is the whole wire
        def _usage(self): return None
        def _send(self, msg, **kw):
            calls.append(tool_channel(self.spec))
            if calls[-1] == 'native': raise RuntimeError('mcp_servers disallowed by policy')
            return 'answered'

    b = Refusing(CC, tools=[lambda: None])
    try:
        assert b.send('hi') == 'answered'
        assert calls == ['native', 'tags']         # tried the wire, learned, and finished the turn
        assert any('travel in the system prompt' in p for p in b.problems)
        assert tool_channel(CC) == 'tags'          # and the next turn does not try the wire again
    finally: forget_forced_tags()


def test_the_tags_channel_is_paid_for_out_of_the_window_it_shares(monkeypatch):
    """What the tags channel costs the briefing. Rishi appends the schemas to the system prompt
    after everything here has finished deciding what fits, so a window sized as if they were free
    is a window that overflows by the size of the tool set."""
    tight = ModelSpec('tight', 'remote', 'x', SMALL_CTX + 1000)
    assert budget_for(tight, 6000).note == 'full briefing'      # native: comfortably above SMALL_CTX
    assert budget_for(tight, 6000, 'tags').drop                 # tags: the schemas push it under
    assert budget_for(BIG, 6000, 'tags').note == 'full briefing'  # and 200k does not care


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

    sent = Tagged(CC); sent.send('go')
    assert any('came back as prose' in p for p in sent.problems), sent.problems
    streamed = Tagged(CC); ''.join(streamed.stream('go'))
    assert any('came back as prose' in p for p in streamed.problems), streamed.problems
    clean = Clean(CC); clean.send('go')
    assert not clean.problems


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
        from rishi.core import mk_toolspec
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
    assert budget - now > 1500, f'only {budget - now} left to answer in'
    # A 200k model is untouched by any of it: the old cost was never its problem.
    assert was < threshold(BIG.ctx)


# -- what the briefing says about the tools --------------------------------------------

def test_the_briefing_describes_only_the_tools_the_model_was_given():
    """A rule about `run_shell` on a host that cannot run commands costs the model a wasted turn
    discovering that -- which is how the briefing came to describe a `scale_numeric` that no longer
    existed, and to promise verification the harness had no way to perform."""
    assert 'run_shell' in A.work_rules(['run_shell'])
    assert 'run_shell' not in A.work_rules(['view_file'])
    assert 'run_shell' in A.work_rules()          # no filter means the whole thing

    # The response-order rule and durable-memory rule are both included in the briefing.
    # lead with the answer, and look in durable memory before acting.
    rules = A.work_rules()
    assert 'Start every user-facing response with what you plan to do or the next action.' in rules
    assert 'Before acting on a request, search Vishalakshi durable memory with `memory_search`' in rules

    h = FullHost(files={'a.py': 'x = 1\n'})
    sp = A.system_prompt(h, tools=tools_for(h))
    for t in {t.__name__ for t in tools_for(h)} & {n for n, _ in A.RULES if n}: assert t in sp
    assert 'delegate_parallel' not in sp          # this host offers no sub-agents


def test_the_coding_standard_reaches_the_briefing_it_was_written_for(host):
    """`coding_patterns` names Ramabana's own tools, and reached no model on any backend. It was
    dropped from `skills` under the default profile -- so it was missing from the index as well,
    and `system_prompt`'s inline loop skipped a name it could not find without saying so."""
    big = Agent(host, extensions=False, subagents=False)
    big.routing.spec = lambda job='turn', fallback=True: BIG
    assert 'coding_patterns' in {s.name for s in big.skills}
    sp = big.system_prompt()
    assert '## coding_patterns' in sp and 'Every construct must earn its place' in sp

    small = Agent(host, extensions=False, subagents=False)
    small.routing.spec = lambda job='turn', fallback=True: SMALL
    assert 'earn its place' not in small.system_prompt()   # the budget still decides


def test_the_tags_channel_hears_the_output_contract_after_the_tool_protocol():
    """Rishi appends the tag protocol *after* the briefing, so on that channel the last thing the
    model reads is tool punctuation and the style rules are a whole briefing away. Riding out with
    the turn is the only position later than that. Every other channel already has a system
    message and is left alone."""
    native = ModelSpec('gpt', 'remote', 'gpt-5.6', 200_000)
    # stated rather than inherited: whether an agent harness is on tags now depends on which SDKs
    # this machine has, and that is not what this test is about
    import ramabana.core as _core
    _real, _core._agent_native = _core._agent_native, lambda rt: False
    try:
        _output_contract_cases(native)
    finally: _core._agent_native = _real

    # It restates the briefing's own rule rather than introducing a second instruction system.
    assert 'plain sentences' in A.work_rules() and 'plain sentences' in A.OUTPUT_CONTRACT


def _output_contract_cases(native):
    for spec, tagged in ((CURSOR, True), (CLAUDE, True), (native, False)):
        a, be = fake_agent(replies=['done'])
        a.routing.spec = lambda job='turn', fallback=True, _s=spec: _s
        a.ask('what does budget_for decide?')
        assert ('<output-contract>' in str(be.sent[-1])) is tagged, spec.name


def test_the_projects_own_instructions_are_read_marked_and_bounded():
    """Every other harness reads `AGENTS.md`, so a repository could not tell this agent what it
    tells every other one. It is marked with its path so the model can tell a project rule from
    something the harness made up, and truncated rather than dropped past the point where it is
    documentation instead of instructions."""
    from ramabana.testing import MemHost
    h = MemHost({'/proj/AGENTS.md': 'Use uv, never pip.'})
    ctx = A.project_context(h)
    assert 'Use uv, never pip.' in ctx and 'path="/proj/AGENTS.md"' in ctx
    assert A.project_context(MemHost()) == ''

    big = MemHost({'/proj/AGENTS.md': 'x' * (A.MAX_CONTEXT_FILE + 500)})
    over = A.project_context(big)
    assert 'truncated' in over and len(over) < A.MAX_CONTEXT_FILE + 800

    reaches = MemHost({'/proj/AGENTS.md': 'Run the tests with `nbdev-test`.'})
    assert 'nbdev-test' in A.system_prompt(reaches, tools=tools_for(reaches))


# -- what rides along with a prompt ----------------------------------------------------

def test_the_ramabana_profile_does_not_mix_in_the_aai_notices():
    """Two instruction systems in one prompt is how a model ends up told to do opposite things.
    The aai profile stays available as an explicit compatibility option, chosen at construction."""
    from ramabana import runtime
    plain, be = fake_agent(replies=['done'])
    plain.ask('add a test')
    assert runtime.ACTION_NOTICE not in str(be.sent[-1])

    aai, abe = fake_agent(replies=['done'], instruction_style='aai')
    aai.ask('add a test')
    assert runtime.ACTION_NOTICE in str(abe.sent[-1])


def test_a_notice_fires_on_the_shape_of_the_prompt_not_on_a_model_call():
    "Deterministic, so the routing is inspectable in the conversation history afterwards."
    from ramabana import runtime
    assert runtime.prompt_notices('where is this handled?') == [runtime.Q_NOTICE]
    assert runtime.APPROVAL_NOTICE in runtime.prompt_notices('go')
    assert runtime.APPROVAL_NOTICE in runtime.prompt_notices('ok.')
    assert runtime.BTW_NOTICE in runtime.prompt_notices('BTW can you also check the tests')
    assert runtime.prompt_notices('add a test for this') == [runtime.ACTION_NOTICE]
    assert '<system-reminder>' in runtime.notices_block('what does this do?')
    assert runtime.ACTION_NOTICE in runtime.notices_block('add a test')

    a, be = fake_agent(replies=['because x'])
    a.ask('why does this break?')
    sent = str(be.sent[0])
    assert 'route="direct"' in sent and '<system-reminder>' not in sent


def test_a_delegated_question_runs_on_a_thrown_away_conversation_with_the_scope_it_needs(spec):
    """Nothing leaks back into the parent -- a sub-agent whose context returns is a slower way of
    doing the work inline. It keeps the scope choice, because the sandbox limits the Python available
    and not what may be seen: the overlay is protected by the AST policy rather than an allowlist,
    so it is no more dangerous to delegate than to run.
    """
    import inspect
    from ramabana.tools import NullHost, delegate, read_only
    be = FakeBackend(spec)
    be.start()
    assert delegate(be, 'where do we do X?', tools=[]) == 'sub answer'
    assert len(be.spawned) == 1 and be.hist == []

    class H(NullHost):
        def __init__(self, *a, **kw): super().__init__(*a, **kw); self.calls = []
        def inspect_python(self, code, scope='isolated'):
            self.calls.append((code, scope)); return 'ok'
        def list_vars(self): return 'df: DataFrame'
        def terminal_text(self, lines=200): return ''
        def run_python(self, code): return 'ok'

    h = H(['/x'])
    sub = {t.__name__: t for t in read_only(tools_for(h))}
    assert 'inspect_python' in sub
    assert 'scope' in inspect.signature(sub['inspect_python']).parameters
    sub['inspect_python'](code='list(df.columns)', scope='overlay')
    assert h.calls == [('list(df.columns)', 'overlay')]
