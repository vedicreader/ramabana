"""The briefing: what a model is told, what it is sent back, and what the project tells it.

This repository already has two test tiers, and this file is deliberately the second one. The
notebooks in `nbs/` carry a `## Tests` section each, written to be read: they print what they
checked, and `00_core.ipynb` is where the budget *arithmetic* lives, in a form you can follow.
What is here is the *wiring* and the *contracts* -- the things a reader of the notebooks would
not notice had broken, run in bulk.

So the arithmetic is not repeated here. Each test below names one contract, and the last one is
the end-to-end property all of it exists for: that a turn on a small local model fits in its
window. That one would have caught every bug the others were written for.

Compaction under a full briefing belongs to the window rather than to the briefing, and lives in
`test_context.py` with the rest of that block.

Nothing here loads a model. A `ModelSpec` is the whole input the budget takes, so a spec
standing in for an uninstalled engine tests exactly what a real one would.
"""

import pytest

from ramabana import runtime
from ramabana import agent as A
from ramabana.agent import Agent
from ramabana.core import (Budget, ModelSpec, budget_for, force_tags, forget_forced_tags,
                           tool_channel)
from ramabana.runtime import estimate_tokens, threshold
from ramabana.testing import FakeBackend, FullHost, ScriptedBackend, Step
from ramabana.tools import LocalHost, Skill, clip_lines, named_skills, sub_sp, tools_for

SMALL = ModelSpec('gemma-e2b', 'litert', 'litert-community/x', 16_384)   # the local default
BIG = ModelSpec('sonnet', 'remote', 'claude-sonnet-4-5', 200_000)
CC = ModelSpec('cc', 'remote', 'claude_code/claude-sonnet-5', 200_000)

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
    """One contract with four halves, asserted together because they are one decision: a small
    window loses the research groups it could not use, does not get a skill body inlined, gets a
    smaller clip, and says so. `read_skill` still reaches the skill, so this costs a call rather
    than a capability."""
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


# -- where the tool schemas travel -----------------------------------------------------

def test_the_tool_channel_is_one_decision(monkeypatch):
    """`native` is the default and better wherever the wire is open. A refused channel is
    remembered per model so the lesson costs one turn rather than every turn, and the environment
    forces either for a machine broken in a way nothing here detects."""
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
    """The one test that would have caught every bug the others were written for.

    A real `Agent` on the 16k model that ships as the local default, running a real four-call
    turn through its real tools, with the whole prompt measured the way the engine will see it:
    briefing, plus what four tool results actually cost. Under the old settings it does not fit,
    which is the point -- that was not a slow agent, it was one that could not finish a turn.
    """
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

    h = FullHost(files={'a.py': 'x = 1\n'})
    sp = A.system_prompt(h, tools=tools_for(h))
    for t in {t.__name__ for t in tools_for(h)} & {n for n, _ in A.RULES if n}: assert t in sp
    assert 'delegate_parallel' not in sp          # this host offers no sub-agents


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
