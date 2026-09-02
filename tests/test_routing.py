"""Routing: which model runs which job, and what happens when a runtime is missing.

Nothing here loads a model — `Routing` and `resolve` deal in `ModelSpec`s.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from ramabana import agent, core
from ramabana.agent import Agent
from ramabana.core import (DEFAULT_POLICY, LOCAL, MODELS, ONESHOT_JOBS, ModelSpec, Routing,
                           available_models, register_model, resolve)
from ramabana.runtime import RishiBackend, make_backend
from ramabana.testing import FakeBackend, MemHost, fake_agent


def child(code):
    "Run `code` in a fresh interpreter, for the facts that are about import side effects."
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


# -- the policy ------------------------------------------------------------------------

def test_the_one_shot_model_is_named_once_and_moves_every_cheap_job(monkeypatch):
    "Turn model is independent of oneshot; oneshot moves every cheap job; env can override one job."
    assert LOCAL['gemma-e4b'] == 'litert-community/gemma-4-E4B-it-litert-lm'
    assert DEFAULT_POLICY['oneshot'] == 'gemma-e4b'

    r = Routing(turn='gpt-mini')
    for job in ONESHOT_JOBS: assert r.name_for(job) == 'gemma-e4b', job
    assert r.name_for('turn') == 'gpt-mini' and r.name_for('subagent') == 'gpt-4.1'
    # a summary of this conversation belongs on the model holding it. Under the `oneshot` policy
    # it loaded a second local runtime to summarise the first.
    assert 'summary' not in ONESHOT_JOBS and r.name_for('summary') == 'gpt-mini'

    r.policy['oneshot'] = 'gpt-sol'                    # one name moves them all
    for job in ONESHOT_JOBS: assert r.name_for(job) == 'gpt-sol', job
    assert r.name_for('summary') == 'gpt-mini', 'except the one that follows the turn'
    r.policy['summary'] = 'gpt'                        # and it may still be singled out
    assert r.name_for('summary') == 'gpt' and r.name_for('classify') == 'gpt-sol'

    monkeypatch.delenv('LEELA_MODEL', raising=False)
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r2 = Routing(turn='gemma-e2b')
    assert r2.spec('summary').name == 'gemma-12b'
    assert r2.spec('classify').name == core.DFLT_LOCAL

    r2.set('gemma-12b')                                # stand-in for a cloud turn, no network
    assert r2.spec('turn').name == 'gemma-12b'
    for job in ('completion', 'classify'):
        assert r2.spec(job).name == core.DFLT_LOCAL and r2.spec(job).local, job
    assert r2.spec('subagent').name == 'gpt-4.1' and not r2.spec('subagent').local


def test_a_model_that_is_not_here_moves_a_cheap_job_and_never_the_turn(hide_runtime):
    "Missing oneshot runtime falls back with a note; a missing turn model raises."
    hide_runtime('mlx')
    r = Routing(turn='gpt-mini')
    r.policy['oneshot'] = 'mlx/not-installed-here'
    with pytest.raises(Exception): r.spec('oneshot', fallback=False)
    assert r.spec('classify').name == 'gpt-mini'       # the turn model, which is by definition here
    assert 'unavailable' in r.notes['classify']

    with pytest.raises(Exception): Routing(turn='mlx/not-installed-here').spec('turn')

    assert not core.runtime_available('mlx')
    assert all(row['provider'] != 'mlx' for row in available_models())
    with pytest.raises(RuntimeError, match=r'install rishi\[mlx\]'):
        resolve('mlx/mlx-community/example')


def test_a_short_name_is_checked_for_its_runtime_like_a_long_one(hide_runtime):
    "Catalogue short names and `runtime/model` specs both refuse an uninstalled runtime."
    pairs = (('qwen-4b', 'mlx', 'mlx/mlx-community/Qwen3.5-4B-MLX-4bit'),
             ('gemma-e4b', 'litert', 'litert/litert-community/gemma-4-E4B-it-litert-lm'))
    for short, runtime, long in pairs:
        assert MODELS[short][0] == runtime   # the catalogue, never the venv
        hide_runtime(runtime)                # absence is stated, so `rishi[all]` cannot mask it
        with pytest.raises(RuntimeError, match='unavailable'): resolve(short)
        with pytest.raises(RuntimeError, match='unavailable'): resolve(long)


def test_a_name_is_resolved_or_refused_but_never_guessed():
    "Silently running a typo on a frontier model is the kind of surprise that shows up on a bill."
    with pytest.raises(KeyError): resolve('sonnnet')
    s = resolve('somevendor/some-model')              # but an unlisted spec is taken at face value
    assert (s.backend, s.model_id) == ('remote', 'somevendor/some-model') and s.ctx > 0
    for name in ('gemma-e2b', 'gemma-e4b', 'sonnet'): # and everything runs through the one adapter
        assert isinstance(make_backend(resolve(name)), RishiBackend)


def test_an_unknown_prefix_is_read_as_a_vendor_and_handed_to_remote():
    """The fall-through every `vendor/model` spec depends on.

    `prefix_typo` used to catch the one slip this cannot absorb -- `claude-code/` for
    `claude_code/` -- but no runtime prefix contains a `-` or `_` any more, so there is nothing
    left for it to catch and it went with the transport it was written for.
    """
    assert resolve('openai/gpt-5.6').backend == 'remote'
    assert resolve('claude/claude-sonnet-5').backend == 'claude'

def test_changing_the_turn_model_carries_the_conversation_and_is_refused_mid_turn(monkeypatch):
    "A new Rishi backend starts lazily with the old backend's canonical history, copied not shared."
    made = []

    class SwitchBackend(FakeBackend):
        def close(self): self.chat = None

    def build(spec, **kw):
        b = SwitchBackend(spec, replies=['continued'], **kw)
        made.append(b)
        return b

    monkeypatch.setattr(agent, 'make_backend', build)
    a = Agent(MemHost(), model='gemma-e2b', extensions=False, subagents=False)
    first = a.start()
    first.hist_.extend([{'role': 'user', 'content': 'remember cedar'},
                        {'role': 'assistant', 'content': 'I will remember cedar'}])

    a.set_model('gemma-12b')
    assert a.model.name == 'gemma-12b' and not a.ready
    second = a.start()
    assert second is made[-1]
    assert second.hist == first.hist_ and second.hist is not first.hist_

    b, _ = fake_agent()
    run = b._new_run('still working')
    with pytest.raises(RuntimeError, match='while the assistant is working'):
        b.set_model('gemma-12b')
    run.finish()


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


# -- the seam --------------------------------------------------------------------------

def test_ramabana_does_not_import_leela():
    "Generated modules must not import leela."
    import ramabana
    bad = [f'{f.name}:{n}' for p in ramabana.__path__ for f in Path(p).glob('*.py')
           for n, line in enumerate(f.read_text().splitlines(), 1)
           if line.startswith(('from leela', 'import leela'))]
    assert not bad, 'ramabana must not import from leela:\n' + '\n'.join(bad)


def test_a_retired_prefix_says_where_the_model_went():
    """An id from an old config must not be read as a vendor.

    `claude_code/...` and `cursor/...` both routed somewhere once. With the prefixes gone they fell
    through to `remote` as if `claude_code` were a vendor, which asks for an API key nothing about
    the request needs -- a credentials error several layers from the cause.
    """
    with pytest.raises(KeyError, match='claude/'):
        resolve('claude_code/claude-sonnet-5')
    with pytest.raises(KeyError, match='removed'):
        resolve('cursor/composer-2.5')
    assert resolve('openai/gpt-5.6').backend == 'remote'      # a real vendor still falls through


def test_an_unknown_model_names_the_near_miss_rather_than_the_whole_table():
    """A dot for a hyphen printed all 44 known names and left the reader to spot it.

    The list is the least useful part of the message: what the typist wants is the name they nearly
    typed. `/models` is there for the rest.
    """
    with pytest.raises(KeyError) as e:
        resolve('claude-sonnet-4.6')
    msg = str(e.value)
    assert 'claude-sonnet-4-6' in msg, msg
    assert 'did you mean' in msg.lower(), msg
    assert '/models' in msg, msg
    assert 'gemma-e2b' not in msg, 'the whole table is still in the message'

    # a name nothing is close to says so plainly, and still does not list everything
    with pytest.raises(KeyError) as e:
        resolve('wat')
    assert 'gemma-e2b' not in str(e.value) and '/models' in str(e.value), str(e.value)


def test_a_typed_model_name_fails_as_a_sentence_not_a_traceback():
    """`--model claude-sonnet-4.6` printed thirty frames of `fastcore.script` and buried the message.

    Everything else `main` refuses -- a bad theme, a missing pyrepl extra, `--vault` without a host --
    already prints one line and returns 2. Model resolution was the one that raised through.
    """
    import subprocess, sys, pathlib
    exe = pathlib.Path(sys.executable).parent/'ramabana'
    if not exe.exists(): pytest.skip('console script not installed in this env')
    r = subprocess.run([str(exe), '--model', 'claude-sonnet-4.6', 'hi'],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert 'Traceback' not in r.stderr, r.stderr
    assert 'claude-sonnet-4-6' in r.stderr, r.stderr
    assert r.stderr.count('\n') <= 2, f'{r.stderr.count(chr(10))} lines: {r.stderr}'

def test_a_remedy_names_an_extra_only_where_rishi_still_declares_one():
    """Telling someone to install an extra rishi does not declare sends them to do nothing and come
    back to the same error: pip reports an unknown extra as a warning and installs nothing.

    `rishi[claude]`, `[copilot]` and `[remote]` went when rishi took those dependencies on itself,
    and `[litert]` went the same way in 0.1.32."""
    import importlib.metadata as md, re
    from ramabana.core import RUNTIMES, runtime_remedy
    declared = set(md.metadata('rishi').get_all('Provides-Extra') or [])
    assert 'litert' not in declared, 'litert-lm-api is a base dependency now'
    for r in RUNTIMES:
        remedy = runtime_remedy(r)
        assert remedy, f'{r} has no answer'
        named = re.search(r'pip install rishi\[([\w-]+)\]', remedy)
        if named: assert named[1] in declared, f'{r} names an extra rishi does not declare'
    assert 'ships with rishi' in runtime_remedy('litert')
    assert 'claude /login' in runtime_remedy('claude')
    assert 'sign in' in runtime_remedy('copilot')
    assert 'API key' in runtime_remedy('remote')


def test_a_harness_is_reachable_through_its_module_and_its_binary():
    """`rishi.claude` lost `sdk_available` when it became SDK-only, and the probe kept calling it
    inside a bare except -- so the check silently became binary-only and swallowed real errors."""
    import ramabana.core as core
    assert 'sdk_available' not in core._harness_available.__doc__
    src = core._harness_available.__code__.co_names
    assert 'sdk_available' not in src, 'the removed limb is gone, not merely unreachable'
    assert core._harness_available('rishi.does_not_exist', 'nope') is False
    assert core._harness_available('rishi.claude', 'no_such_probe') is False

def test_a_claude_model_is_measured_against_its_own_window():
    """Every harness model used to be charged a flat 128k, because a harness re-sent the whole
    conversation each turn and the ceiling was what that cost. Rishi resumes a session now, so the
    same conversation was reading about eight times fuller on Claude than on a 1M OpenAI model."""
    from ramabana.core import CLAUDE_MODELS, DFLT_AGENT_CTX, claude_ctx, resolve
    for mid in CLAUDE_MODELS:
        want = 200_000 if mid.startswith(('claude-opus', 'claude-sonnet')) else DFLT_AGENT_CTX
        assert resolve(mid).ctx == want, mid
    assert resolve('opus').ctx == 200_000 and resolve('sonnet').ctx == 200_000, 'aliases too'
    # a window we do not know falls back rather than being guessed at: a ceiling set too high
    # hides a compaction that should already have happened
    assert claude_ctx('claude-something-unreleased') == DFLT_AGENT_CTX
    assert claude_ctx('') == DFLT_AGENT_CTX and claude_ctx(None) == DFLT_AGENT_CTX
    assert resolve('gpt-4.1').ctx > 1_000_000, 'and a hosted model still reports its real window'


def test_a_bigger_window_does_not_quietly_change_what_a_model_is_briefed_with():
    "Both ceilings sit above `SMALL_CTX`, so the tool budget must be the same either way."
    from ramabana.core import DFLT_AGENT_CTX, budget_for, resolve
    before, after = budget_for(resolve('claude-haiku-4-5'), 6000), budget_for(resolve('claude-opus-5'), 6000)
    assert before.drop == after.drop == () and before.inline is after.inline is True

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


def test_occupancy_comes_from_the_session_rather_than_a_local_estimate():
    """Claude Code reports what its own window holds, and rishi refreshes that once per turn on the
    loop. Ramabana takes the default `stateful=True`, which is the path that refreshes it."""
    from rishi.claude import ClaudeChat
    import inspect
    assert '_ctx_live' in inspect.getsource(ClaudeChat.token_count.fget), 'the session number wins'
    assert inspect.signature(ClaudeChat.__init__).parameters['stateful'].default is True
    import ramabana.runtime as R
    assert 'stateful' not in inspect.getsource(R.Backend.start), 'ramabana does not override it'

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

def test_an_engine_that_gave_what_was_asked_is_left_alone():
    spec = ModelSpec('gguf-thing', 'llama', 'someone/Thing-GGUF', 32_768)
    be, _ = _started(spec, 32_768)
    assert be.spec.ctx == 32_768

def test_a_wider_engine_does_not_widen_the_window_behind_the_agent():
    "Only downwards. A window the agent did not ask for is one nothing has budgeted for."
    spec = ModelSpec('gguf-thing', 'llama', 'someone/Thing-GGUF', 32_768)
    be, _ = _started(spec, 262_144)
    assert be.spec.ctx == 32_768

def test_an_engine_with_nothing_to_say_about_its_window_is_not_an_error():
    "Hosted runtimes have no engine at all, and a local one may predate `n_ctx`."
    spec = ModelSpec('cloud-thing', 'remote', 'openai/gpt-4.1', 128_000)
    from ramabana.runtime import use_chat
    class Bare:
        ctx_limit = None
        def close(self): pass
    be = RishiBackend(spec)
    with use_chat(lambda model_id, **kw: Bare()): be.start()
    assert be.spec.ctx == 128_000

def test_a_gguf_engine_is_asked_for_the_window_the_spec_promises():
    """llama.cpp builds its KV cache at load and defaults to 8192 whatever the model was trained
    for, so the engine held a quarter of what `ctx_limit` advertised."""
    spec = ModelSpec('gguf-thing', 'llama', 'someone/Thing-GGUF', 32_768)
    _, seen = _started(spec, 32_768)
    assert seen['n_ctx'] == 32_768 and seen['ctx_limit'] == 32_768

def test_a_gguf_window_the_caller_chose_is_left_alone():
    spec = ModelSpec('gguf-thing', 'llama', 'someone/Thing-GGUF', 32_768)
    _, seen = _started(spec, 4096, n_ctx=4096)
    assert seen['n_ctx'] == 4096

def test_only_the_gguf_runtime_is_given_n_ctx():
    "MLX reads the window from the model's own config, and a hosted runtime has none to build."
    for runtime, mid in (('mlx', 'mlx-community/Thing-4bit'), ('remote', 'openai/gpt-4.1')):
        _, seen = _started(ModelSpec('x', runtime, mid, 32_768), 32_768)
        assert 'n_ctx' not in seen, runtime

def _measured(spec, real, monkeypatch, **kw):
    "The window a backend settles on, given a model config that reports `real`."
    monkeypatch.setattr('ramabana.runtime.local_window', lambda runtime, mid: real)
    be, seen = _started(spec, spec.ctx, **kw)
    return be.spec.ctx, seen

def test_a_model_trained_smaller_than_the_table_is_not_filled_to_the_table(monkeypatch):
    """`_LOCAL_CTX` is hand-kept and everything missing from it took the default. Packed to a window
    the model never had, a turn either died mid-tool or came back hallucinated."""
    spec = ModelSpec('small', 'mlx', 'mlx-community/Small-4bit', 32_768)
    ctx, _ = _measured(spec, 8192, monkeypatch)
    assert ctx == 8192, 'the model config, not the table'

def test_a_model_trained_wider_than_the_table_is_still_capped(monkeypatch):
    """A config is the model's maximum, not a suggestion. Ornith-9B declares 262144, and an agent
    that budgets that much fills a KV cache until the machine gives out."""
    spec = ModelSpec('ornith-9b', 'mlx', 'mlx-community/Ornith-1.0-9B-8bit', 32_768)
    ctx, _ = _measured(spec, 262_144, monkeypatch)
    assert ctx == 32_768, 'the table caps how much of a local model is worth filling'

def test_a_model_config_that_says_nothing_leaves_the_table_alone(monkeypatch):
    spec = ModelSpec('quiet', 'mlx', 'mlx-community/Quiet-4bit', 32_768)
    ctx, _ = _measured(spec, 0, monkeypatch)
    assert ctx == 32_768

def test_a_hosted_model_is_never_measured(monkeypatch):
    "There is no config to read and no engine to build; the window is the provider's own number."
    called = []
    monkeypatch.setattr('ramabana.runtime.local_window', lambda runtime, mid: called.append(mid) or 8192)
    _started(ModelSpec('cloud', 'remote', 'openai/gpt-4.1', 128_000), 128_000)
    assert not called

def test_the_engine_is_asked_for_the_window_the_model_config_settled_on(monkeypatch):
    "Measured first, so llama.cpp builds the cache for what the model has rather than for a guess."
    spec = ModelSpec('gguf', 'llama', 'someone/Thing-GGUF', 32_768)
    ctx, seen = _measured(spec, 8192, monkeypatch)
    assert ctx == 8192 and seen['n_ctx'] == 8192

def test_an_ollama_model_resolves_to_the_ollama_runtime(monkeypatch):
    """`ollama/` fell through every branch and came back as `remote`, so a local daemon model was
    dialled as a hosted API and failed on a missing key rather than saying it was not wired."""
    monkeypatch.setattr(core, 'runtime_available', lambda r: True)
    s = resolve('ollama/ornith-1.5:9b')
    assert (s.runtime, s.model_id) == ('ollama', 'ornith-1.5:9b')
    assert s.local, 'it runs on this machine, so it is not a hosted spend'

def test_ollama_is_a_runtime_ramabana_knows_about():
    assert 'ollama' in core.RUNTIMES and 'ollama' not in core.HOSTED

def test_an_ollama_runtime_that_cannot_be_reached_says_so(monkeypatch):
    monkeypatch.setattr(core, 'runtime_available', lambda r: r != 'ollama')
    with pytest.raises(RuntimeError, match='ollama runtime is unavailable'):
        resolve('ollama/ornith-1.5:9b')

def test_the_ollama_daemon_is_asked_for_the_window_it_holds(monkeypatch):
    "`num_ctx` defaults to 4096 whatever the model holds, the same trap llama.cpp sets with `n_ctx`."
    monkeypatch.setattr('ramabana.runtime.local_window', lambda runtime, mid: 262_144)
    spec = ModelSpec('ornith', 'ollama', 'ornith-1.5:9b', 32_768)
    ctx, seen = _measured(spec, 32_768, monkeypatch)
    assert ctx == 32_768, 'capped, since a daemon will happily hold a window nothing budgeted for'
    assert seen['n_ctx'] == 32_768, 'and the daemon is told, rather than left on its 4096 default'


def test_a_harness_that_is_installed_but_broken_says_which_half_failed(monkeypatch):
    """`runtime_available` answers yes or no and swallows the reason, so a harness whose module
    raises read as "not installed" with nothing naming the cause. `runtime_detail` is the reason,
    read off the same `HARNESS` table the yes/no is read off, so the two cannot disagree."""
    import sys, types
    from ramabana import core

    assert core.runtime_detail('remote') == '', 'only a harness has a module to fail'
    assert core.runtime_detail('nothing-like-this') == ''

    monkeypatch.setitem(core.HARNESS, 'claude', ('no_such_module_at_all', 'claude_bin'))
    got = core.runtime_detail('claude')
    assert got == "import no_such_module_at_all: ModuleNotFoundError: No module named 'no_such_module_at_all'", got
    assert core.runtime_available('claude') is False, 'the reason and the yes/no agree'

    mod = types.ModuleType('probe_harness')
    monkeypatch.setitem(sys.modules, 'probe_harness', mod)
    monkeypatch.setitem(core.HARNESS, 'claude', ('probe_harness', 'probe'))

    mod.probe = lambda: None
    assert core.runtime_detail('claude') == 'probe() found nothing'
    mod.probe = lambda: (_ for _ in ()).throw(FileNotFoundError('claude is not on $PATH'))
    assert core.runtime_detail('claude') == 'probe(): FileNotFoundError: claude is not on $PATH'
    mod.probe = lambda: '/usr/bin/claude'
    assert core.runtime_detail('claude') == '', 'a reachable harness has nothing to report'
    assert core.runtime_available('claude') is True
