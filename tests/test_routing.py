"""Routing: which model runs which job, and what happens when a runtime is missing.

Nothing here loads a model — `Routing` and `resolve` deal in `ModelSpec`s.
"""
import pytest

from ramabana import agent, core
from ramabana.agent import Agent
from ramabana.core import ModelSpec, Routing, available_models, register_model, resolve
from ramabana.runtime import RishiBackend, make_backend
from ramabana.testing import FakeBackend, MemHost


# -- the policy ------------------------------------------------------------------------

def test_a_model_that_is_not_here_moves_a_cheap_job_and_never_the_turn(hide_runtime, monkeypatch):
    "Missing oneshot runtime falls back with a note; a missing turn model raises."
    hide_runtime('mlx')
    monkeypatch.setenv('OPENAI_API_KEY', 'x')
    r = Routing(turn='gpt-mini')
    r.policy['oneshot'] = 'mlx/not-installed-here'
    with pytest.raises(Exception): r.spec('oneshot', fallback=False)
    assert r.spec('inline').name == 'gpt-mini'       # the turn model, which is by definition here
    assert 'unavailable' in r.notes['inline']

    with pytest.raises(Exception): Routing(turn='mlx/not-installed-here').spec('turn')

    assert not core.runtime_available('mlx')
    assert all(row['provider'] != 'mlx' for row in available_models())
    with pytest.raises(RuntimeError, match=r'install rishi\[mlx\]'):
        resolve('mlx/mlx-community/example')


def test_a_name_is_resolved_or_refused_but_never_guessed():
    "Silently running a typo on a frontier model is the kind of surprise that shows up on a bill."
    with pytest.raises(KeyError): resolve('sonnnet')
    s = resolve('somevendor/some-model')              # but an unlisted spec is taken at face value
    assert (s.backend, s.model_id) == ('remote', 'somevendor/some-model') and s.ctx > 0
    for name in ('gemma-e2b', 'gemma-e4b', 'sonnet'): # and everything runs through the one adapter
        assert isinstance(make_backend(resolve(name)), RishiBackend)


# -- what reaches the engine -----------------------------------------------------------

def test_saved_options_and_engine_selection_reach_rishi(monkeypatch):
    "A registered model's transport options and the LiteRT backend switch are both `_runtime_kw`."
    spec = register_model('private-api', 'openai/private-model', 'remote', 64_000,
                          base_url='https://api.example.test/v1', api_key_env='PRIVATE_API_KEY')
    monkeypatch.setenv('PRIVATE_API_KEY', 'secret')
    kw = RishiBackend(spec)._runtime_kw()
    assert kw['base_url'].endswith('/v1') and kw['api_key'] == 'secret'

    from litert_lm import Backend as LB
    monkeypatch.setenv('RAMABANA_LITERT_BACKEND', 'gpu')
    # `backend=` is rishi's own argument; `create_engine` builds the engine from a parameter of
    # that name, so an accelerator buried in `eng_kw` arrived as a second value for it.
    kw = RishiBackend(resolve('gemma-e4b'))._runtime_kw()
    assert isinstance(kw['backend'], LB.GPU) and 'backend' not in kw['eng_kw']
    monkeypatch.setenv('RAMABANA_LITERT_BACKEND', 'cuda')
    with pytest.raises(ValueError, match='use cpu or gpu'):
        RishiBackend(resolve('gemma-e4b'))._runtime_kw()


# -- the Claude Code transport ---------------------------------------------------------

def test_a_tag_tool_call_comes_back_as_a_real_tool_call():
    "The reply is text either way; what changed is that rishi now reads the calls out of it."
    from aidialog.msg_parts import Msg, Text
    import rishi.remote as remote

    class Comp:
        tool_calls, finish_reason, model, usage = None, 'stop', 'claude-sonnet-5', None
        message = Msg(role='assistant', content=[Text(
            'Looking now.\n<tool_call>\n{"name":"search_code","arguments":{"query":"rrf"}}\n</tool_call>')])

    res = remote.norm_completion(Comp())
    assert res['content'] == 'Looking now.'
    assert [(t.name, t.arguments) for t in res['tool_calls']] == [('search_code', {'query': 'rrf'})]


def test_a_remedy_names_an_extra_only_where_rishi_still_declares_one():
    """Telling someone to install an extra rishi does not declare sends them to do nothing and come
    back to the same error: pip reports an unknown extra as a warning and installs nothing.

    `rishi[claude]`, `[copilot]` and `[remote]` went when rishi took those dependencies on itself,
    and `[litert]` went the same way in 0.1.32."""
    import importlib.metadata as md, re
    from ramabana.core import RUNTIME_NAMES, runtime_remedy
    declared = set(md.metadata('rishi').get_all('Provides-Extra') or [])
    assert 'litert' not in declared, 'litert-lm-api is a base dependency now'
    for r in RUNTIME_NAMES:
        remedy = runtime_remedy(r)
        assert remedy, f'{r} has no answer'
        named = re.search(r'pip install rishi\[([\w-]+)\]', remedy)
        if named: assert named[1] in declared, f'{r} names an extra rishi does not declare'
    assert 'ships with rishi' in runtime_remedy('litert')
    assert 'claude /login' in runtime_remedy('claude')
    assert 'sign in' in runtime_remedy('copilot')
    assert 'API key' in runtime_remedy('remote')


def test_a_claude_model_is_measured_against_its_own_window():
    """Every harness model used to be charged a flat 128k, because a harness re-sent the whole
    conversation each turn and the ceiling was what that cost. Rishi resumes a session now, so the
    same conversation was reading about eight times fuller on Claude than on a 1M OpenAI model."""
    from ramabana.core import CLAUDE_MODELS, DFLT_AGENT_CTX, claude_ctx, resolve
    for mid in CLAUDE_MODELS:
        want = 1_000_000 if mid.startswith(('claude-opus-5', 'claude-sonnet-5', 'claude-fable-5', 'claude-haiku-5')) else DFLT_AGENT_CTX
        assert resolve(mid).ctx == want, mid
    assert resolve('opus').ctx == 1_000_000 and resolve('sonnet').ctx == 1_000_000, 'aliases too'
    # a window we do not know falls back rather than being guessed at: a ceiling set too high
    # hides a compaction that should already have happened
    assert claude_ctx('claude-something-unreleased') == DFLT_AGENT_CTX
    assert claude_ctx('') == DFLT_AGENT_CTX and claude_ctx(None) == DFLT_AGENT_CTX
    assert resolve('gpt-4.1').ctx > 1_000_000, 'and a hosted model still reports its real window'


def test_a_window_that_cannot_be_read_keeps_its_last_occupancy():
    """`used_tokens` fell back to `use.total`, which is billing volume accumulated across every
    turn -- so one unreadable session turned a two-thirds-full window into thousands of percent.
    A session that cannot answer has not emptied its window."""
    from ramabana.core import ModelSpec
    from ramabana.runtime import Backend
    b = Backend(ModelSpec('claude/claude-opus-5', 'claude', 'claude-opus-5', 200_000))
    assert b.used_tokens == 0 and b.pct_full == 0.0, 'nothing started, nothing held'

    class Chat: token_count = 137_000
    b.chat = Chat()
    assert b.used_tokens == 137_000 and round(b.pct_full, 3) == 0.685

    class Gone:
        @property
        def token_count(self): raise RuntimeError('the session went away')
    b.chat, b.use.total = Gone(), 4_000_000
    assert b.used_tokens == 137_000, 'the last reading stands'
    assert b.pct_full < 1.0, 'and the bar cannot read past full on billing volume'


class _Engine:
    "An engine that built the cache it could, which may not be the one it was asked for."
    def __init__(self, got): self.got = got
    def n_ctx(self): return self.got

class _Chat:
    def __init__(self, got, ctx_limit=None): self.engine, self.ctx_limit = _Engine(got), ctx_limit
    def close(self): pass

def _started(spec, got, **kw):
    "A backend whose engine reports `got`, without loading anything."
    from ramabana.runtime import use_chat
    seen = {}
    def mk(model_id, **kwargs): seen.update(kwargs); return _Chat(got, kwargs.get('ctx_limit'))
    be = RishiBackend(spec, **kw)
    with use_chat(mk): be.start()
    return be, seen

def test_a_local_engine_is_believed_about_its_own_window():
    """`spec.ctx` is a table. A local engine that could not build the cache that big says so only
    after loading, and the agent packed and compacted against four times what the model held --
    every turn past it dying mid-tool or coming back hallucinated."""
    spec = ModelSpec('gguf-thing', 'llama', 'someone/Thing-GGUF', 32_768)
    be, _ = _started(spec, 8192)
    assert be.spec.ctx == 8192, 'the engine, not the table'
    assert be.chat.ctx_limit == 8192, 'and rishi is told the same, so its own truncation agrees'

def _measured(spec, real, monkeypatch, **kw):
    "The window a backend settles on, given a model config that reports `real`."
    monkeypatch.setattr('ramabana.runtime.local_window', lambda runtime, mid: real)
    be, seen = _started(spec, spec.ctx, **kw)
    return be.spec.ctx, seen

def test_the_engine_is_asked_for_the_window_the_model_config_settled_on(monkeypatch):
    "Measured first, so llama.cpp builds the cache for what the model has rather than for a guess."
    spec = ModelSpec('gguf', 'llama', 'someone/Thing-GGUF', 32_768)
    ctx, seen = _measured(spec, 8192, monkeypatch)
    assert ctx == 8192 and seen['n_ctx'] == 8192

OLD_CLAUDE_IDS = ('claude/claude-opus-5', 'claude-opus-5', 'claude-sonnet-4-6', 'claude/claude-opus-4-8', 'claude-haiku-4-5',
                  'claude/claude-haiku-4-5', 'claude/opus-5', 'claude/sonnet', 'claude/haiku', 'claude-sonnet-5', 'claude/claude-fable-5-1')

def test_a_model_id_the_catalog_moved_past_still_resolves(monkeypatch):
    """Histories and pinned settings carry the ids that were current when they were written. Resume
    validates the logged model name, so an id the picker no longer lists must still resolve: the
    picker shows what is current, and Claude Code decides what it still serves."""
    import ramabana.core as core
    real = core.runtime_available
    monkeypatch.setattr(core, 'runtime_available', lambda rt: rt == 'claude' or real(rt))
    for name in OLD_CLAUDE_IDS:
        spec, bare = core.resolve(name), name.split('/', 1)[-1]
        assert spec.backend == 'claude' and spec.model_id == core.CLAUDE_ALIASES.get(bare, bare), (name, spec)
    assert core.resolve('opus-5').model_id == 'claude-opus-5'
    assert core.resolve('opus').model_id == core.CLAUDE_ALIASES['opus'], 'a tier alias tracks the latest'
    assert [core.resolve(t).model_id for t in ('sonnet', 'haiku')] == ['claude-sonnet-5-5', 'claude-haiku-5-5'], 'not the older id listed first'
    for name in ('gpt-4.1-mini', 'gpt-5.6', 'gpt-5.5', 'openai/gpt-6-astra', 'codex/gpt-5.4'): assert core.resolve(name).backend == 'remote', name
    with pytest.raises(KeyError): core.resolve('gpt-9')


def no_model_env(monkeypatch):
    for p in ('RAMABANA_', 'LEELA_'):
        for j in ('', *(f'_{j.upper()}' for j in core.JOBS)): monkeypatch.delenv(f'{p}MODEL{j}', raising=False)


# -- a missing OpenAI key falls back without moving Claude jobs -------------------------

def test_without_an_openai_key_medium_jobs_fall_back_and_say_so_once(monkeypatch):
    no_model_env(monkeypatch)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(agent, 'make_backend', lambda spec, **kw: FakeBackend(spec, **kw))
    notes = []
    h = MemHost(); h.note = notes.append
    a = Agent(h, extensions=False, subagents=False)
    for job in ('classify', 'completion'): assert a.routing.spec(job).name == 'claude-haiku-5-5'
    for job in ('oneshot', 'summary', 'inline', 'summary'): assert a._be_or_none(job).spec.name == 'claude-opus-5-5'
    said = [n for n in notes if 'gpt-6.1-luna' in n]
    assert len(said) == 1 and 'OPENAI_API_KEY' in said[0] and 'claude-opus-5-5' in said[0], notes

def test_rishi_usage_is_cumulative_though_its_chat_counts_each_call_afresh():
    """rishi's `Chat` starts a new `use` on every call, while `Agent._finish` diffs a running total.
    A turn smaller than the one before therefore recorded nothing, and `turns` stuck at 0."""
    from types import SimpleNamespace
    from ramabana.core import ModelSpec
    def use(i, o): return SimpleNamespace(model='m', prompt_tokens=i, completion_tokens=o, total_tokens=i + o,
                                          cached_tokens=0, cache_creation_tokens=0, reasoning_tokens=0, cost=0.0, n=1)
    b = RishiBackend(ModelSpec('claude/claude-opus-5-5', 'claude', 'claude-opus-5-5', 200_000))
    b.chat = SimpleNamespace(use=use(100, 10))
    b.use = b._usage()
    assert b.used_tokens == 0, 'the usage baseline is not the window occupancy'
    assert b._usage().input == 100, 'reading again counts the same call once'
    b.chat.use = use(40, 4)                          # the next, smaller call
    b.use = b._usage()
    assert (b.use.input, b.use.turns) == (140, 2)


def test_claude_turns_ask_for_high_effort_unless_told_otherwise(monkeypatch):
    "Claude Code runs a model at its default effort when none is sent, which for Opus 5.5 is medium."
    from ramabana.core import ModelSpec
    spec = ModelSpec('claude/claude-opus-5-5', 'claude', 'claude-opus-5-5', 200_000)
    monkeypatch.delenv('RAMABANA_EFFORT', raising=False)
    assert RishiBackend(spec)._runtime_kw()['effort'] == 'high'
    monkeypatch.setenv('RAMABANA_EFFORT', 'xhigh')
    assert RishiBackend(spec)._runtime_kw()['effort'] == 'xhigh'
    assert RishiBackend(spec, effort='low')._runtime_kw()['effort'] == 'low', 'a configured effort wins'
    assert 'effort' not in RishiBackend(resolve('gemma-e4b'))._runtime_kw()
