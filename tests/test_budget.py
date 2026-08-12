"""Tests for the per-model briefing budget.

The arithmetic itself is checked in `nbs/00_core.ipynb`, where it can be read. What is here is
the *wiring*: that a small window actually reaches `tools_for` and `system_prompt`, that a
model change rebuilds what was sized to the old one, and that nothing is withheld from a model
whose window we could not read.

Nothing here loads a model. A `ModelSpec` is the whole input the budget takes, so a spec
standing in for an uninstalled engine tests exactly what a real one would.
"""

import pytest

from ramabana import runtime
from ramabana.agent import Agent
from ramabana.core import Budget, ModelSpec, TOOL_MAX_FLOOR, budget_for
from ramabana.testing import FakeBackend, FullHost
from ramabana.tools import clip_lines, tools_for

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
    from ramabana.tools import LocalHost
    (tmp_path/'big.txt').write_text('\n'.join(f'line {i} ' + 'x'*60 for i in range(600)))
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


# -- the two holes the budget had ------------------------------------------------------

def test_one_long_line_does_not_escape_the_clip():
    """A minified bundle, a one-line JSON blob or a wide CSV row is a single line, and
    `clip_lines` used to return the first one whole so a result was never empty -- which spent
    a small model's entire window on one tool call."""
    out = clip_lines(['x' * 40_000], n=4096)
    assert len(out) < 4200, len(out)
    assert 'chars' in out and '40000' in out          # counted in chars: no line to resume from
    # A long line reached *after* short ones is still reported by line, so the resume hint works.
    out2 = clip_lines(['short', 'y' * 40_000], n=4096, more='call again from {next}')
    assert 'more line(s) not shown' in out2 and 'call again from 2' in out2
    # And nothing changes for lines that fit.
    assert clip_lines(['a', 'b'], n=4096) == 'a\nb'


def test_a_short_conversation_under_a_big_briefing_still_compacts():
    """The failure this closes: compaction fires on the whole prompt, so on a 16k window with
    Ramabana's briefing in it the conversation is only a few thousand tokens -- smaller than a
    keep-tail measured against the window, so everything was 'recent' and `compact` returned
    'nothing to compact' right up until the engine refused the turn."""
    class Briefed(runtime.Compactor):
        "A compactor told the overhead directly, so the test does not depend on a live engine."
        def __init__(self, overhead, **kw): super().__init__(**kw); self.oh = overhead
        def overhead(self, backend, msgs, count=None): return self.oh

    be = FakeBackend(ModelSpec('gemma-e2b', 'litert', 'x', 16_384))
    be.start()
    # ~7k tokens of conversation: what fits under a 5.2k briefing at the 12,288 threshold.
    be.hist_ = [{'role': 'user', 'content': 'a' * 14_000}, {'role': 'assistant', 'content': 'b' * 14_000},
                {'role': 'user', 'content': 'recent question'}]
    out = Briefed(5_214).compact(be, lambda p, sp: 'GOAL: keep going')
    assert out == 'GOAL: keep going'
    assert be.hist[0]['content'].startswith(runtime.SUMMARY_PREFIX)


def test_the_keep_tail_never_exceeds_half_the_conversation():
    """What guarantees progress no matter how large the briefing is: halving the window only
    happens to work while the overhead is under half of it."""
    c = runtime.Compactor()
    msgs = [{'role': 'user', 'content': 'a' * 4000}, {'role': 'assistant', 'content': 'b' * 4000},
            {'role': 'user', 'content': 'c' * 4000}, {'role': 'assistant', 'content': 'd' * 4000}]
    # An overhead over half a 16k window: the window-based budget alone would keep everything.
    kept = c._keep(msgs, ctx=16_384, overhead=9_000)
    assert 0 < len(kept) < len(msgs), len(kept)


def test_a_large_window_keeps_its_old_keep_tail():
    "The cap must not touch the case that already worked."
    c = runtime.Compactor()
    assert c.budget(200_000, 5_500) == c.keep_recent
    assert c.budget(0) == c.keep_recent                       # no window: unchanged


# -- what a sub-agent is given ---------------------------------------------------------

def test_a_sub_agent_is_sized_to_the_model_sub_agents_run_on(host):
    """`DEFAULT_POLICY` points `subagent` at the small local model, so the default shape is a
    frontier turn delegating to a 16k engine. Handing it the turn model's schemas at the turn
    model's clip is the overflow `Budget` exists to prevent."""
    a = Agent(host, extensions=False, subagents=True)
    a.routing.spec = lambda job='turn', fallback=True: BIG if job == 'turn' else SMALL
    assert a.budget.inline and not a.subagent_budget.inline
    sub = {getattr(t, '__name__', '') for t in a._sub_plain()}
    assert not (sub & RESEARCH)                       # the sub-agent model cannot afford them
    assert RESEARCH <= names(a)                       # the turn model still has them
    assert 'delegate_search' not in sub                # a sub-agent does not delegate


def test_one_model_everywhere_reuses_the_turns_tool_list(host):
    "No reason to build and probe a second list when both models can afford the same briefing."
    a = Agent(host, extensions=False, subagents=True)
    a.routing.spec = lambda job='turn', fallback=True: BIG
    a.tools
    assert a._sub_plain() is a._plain


def test_a_task_can_name_the_skills_it_needs():
    """The caller holds the skill index and the sub-agent does not, so naming a skill is how a
    one-job sub-agent starts holding it instead of spending a step on `read_skill`."""
    from ramabana.tools import Skill, sub_sp, named_skills
    sk = [Skill(name='kosha', source='test', description='code answers', where='test',
                _text='ASK KOSHA LIKE THIS'),
          Skill(name='cfeasy', source='test', description='deploys', where='test',
                _text='DEPLOY LIKE THIS')]
    got, note = named_skills(lambda: sk, 'cfeasy')
    assert [s.name for s in got] == ['cfeasy'] and not note
    brief = sub_sp(skills=got)
    assert 'DEPLOY LIKE THIS' in brief and 'ASK KOSHA' not in brief
    assert sub_sp() == sub_sp(skills=())               # naming nothing changes nothing


def test_a_skill_name_that_matched_nothing_is_reported():
    """A sub-agent quietly briefed without the skill its caller asked for answers from general
    knowledge and sounds exactly as confident as one that had it."""
    from ramabana.tools import Skill, named_skills
    sk = [Skill(name='kosha', source='test', description='d', where='test', _text='t')]
    got, note = named_skills(lambda: sk, 'kosha, nosuchskill')
    assert [s.name for s in got] == ['kosha']
    assert 'nosuchskill' in note and 'kosha' in note


def test_named_skills_reach_the_sub_agents_briefing(host):
    "End to end: the tool the model calls puts the named body in the spawned conversation."
    from ramabana.tools import Skill
    a = Agent(host, extensions=False, subagents=True)
    a.routing.spec = lambda job='turn', fallback=True: BIG
    be = FakeBackend(BIG)
    be.start()
    a._be_or_none = lambda job='turn': be
    a._skills = [Skill(name='cfeasy', source='test', description='deploys', where='test',
                       _text='DEPLOY LIKE THIS')]
    search = next(t for t in a.tools if getattr(t, '__name__', '') == 'delegate_search')
    assert 'sub answer' in search('how do we deploy?', skills='cfeasy')   # what `spawn` scripts
    assert 'DEPLOY LIKE THIS' in be.spawned[0].sp
    # And a name that matched nothing rides back with the answer rather than vanishing.
    assert 'nosuchskill' in search('how do we deploy?', skills='nosuchskill')


# -- where the tool schemas travel -----------------------------------------------------

def test_native_is_the_default_channel():
    "The wire is better wherever it is open: validated schemas, structured calls."
    from ramabana.core import tool_channel
    assert tool_channel(BIG) == 'native'
    assert tool_channel(ModelSpec('cc', 'remote', 'claude_code/claude-sonnet-5', 200_000)) == 'native'


def test_a_refused_wire_channel_is_remembered_per_model():
    """A managed configuration is detectable up front; a transport that refuses MCP for any other
    reason is only learned from a failure, and remembering it keeps the cost at one turn."""
    from ramabana.core import force_tags, forget_forced_tags, tool_channel
    cc = ModelSpec('cc', 'remote', 'claude_code/claude-sonnet-5', 200_000)
    try:
        force_tags(cc.model_id, 'MCP refused by policy')
        assert tool_channel(cc) == 'tags'
        assert tool_channel(BIG) == 'native'          # per model, not a global switch
    finally:
        forget_forced_tags()
    assert tool_channel(cc) == 'native'               # a fixed configuration is tried again


def test_the_channel_can_be_forced_for_any_model(monkeypatch):
    "The escape hatch for a machine whose MCP is broken in a way nothing here detects."
    from ramabana.core import tool_channel
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')
    assert tool_channel(ModelSpec('g', 'remote', 'gpt-5.1', 400_000)) == 'tags'
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'native')
    assert tool_channel(ModelSpec('cc', 'remote', 'claude_code/x', 200_000)) == 'native'


def test_a_tag_call_that_came_back_as_prose_is_reported(monkeypatch):
    """What the tags channel costs. On the wire a malformed call raises; in the prompt it is just
    text, and the user reads it as the model discussing a call it never made."""
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')

    class Tagged(runtime.RishiBackend):
        "A rishi backend whose engine replies with a broken tag, on both paths."
        def _start(self): return self
        def _send(self, msg, **kw): return '<tool_call>{"name": "view_file"'
        def _stream(self, msg, **kw): yield '<tool_call>{"name": '; yield '"view_file"'
        def _usage(self): return runtime.Usage(model=self.spec.model_id)

    be = Tagged(ModelSpec('cc', 'remote', 'claude_code/x', 200_000))
    be.send('go')
    assert any('came back as prose' in p for p in be.problems), be.problems

    streamed = Tagged(ModelSpec('cc', 'remote', 'claude_code/x', 200_000))
    ''.join(streamed.stream('go'))                    # the CLI's path, not `send`'s
    assert any('came back as prose' in p for p in streamed.problems), streamed.problems


def test_a_clean_reply_reports_nothing(monkeypatch):
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')

    class Clean(runtime.RishiBackend):
        def _start(self): return self
        def _send(self, msg, **kw): return 'the answer, with no tags in it'
        def _usage(self): return runtime.Usage(model=self.spec.model_id)

    be = Clean(ModelSpec('cc', 'remote', 'claude_code/x', 200_000))
    be.send('go')
    assert not be.problems
