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
                           available_models, prefix_typo, register_model, resolve)
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
    assert r.name_for('turn') == 'gpt-mini' and r.name_for('subagent') == 'gemma-e4b'

    r.policy['oneshot'] = 'gpt-sol'                    # one name moves them all
    for job in ONESHOT_JOBS: assert r.name_for(job) == 'gpt-sol', job
    r.policy['summary'] = 'gpt'                        # and one may still be singled out
    assert r.name_for('summary') == 'gpt' and r.name_for('classify') == 'gpt-sol'

    monkeypatch.delenv('LEELA_MODEL', raising=False)
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r2 = Routing(turn='gemma-e2b')
    assert r2.spec('summary').name == 'gemma-12b'
    assert r2.spec('classify').name == core.DFLT_LOCAL

    r2.set('gemma-12b')                                # stand-in for a cloud turn, no network
    assert r2.spec('turn').name == 'gemma-12b'
    for job in ('completion', 'classify', 'subagent'):
        assert r2.spec(job).name == core.DFLT_LOCAL and r2.spec(job).local, job


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


def test_a_runtime_misspelled_for_a_vendor_is_caught_where_it_was_typed():
    """`claude-code/...` is the one slip a vendor fall-through cannot absorb.

    It is not a vendor, so it was handed to `remote`, which asked for an `ANTHROPIC_API_KEY` that
    nothing about the request needed -- a credentials error three layers from a hyphen. Only the
    `-`/`_` class of slip is caught: every other prefix is still a real spec taken at face value,
    which is what `openai/gpt-5.6` depends on.
    """
    with pytest.raises(KeyError, match='claude_code/claude-opus-5'):
        resolve('claude-code/claude-opus-5')
    assert prefix_typo('claude-code') == 'claude_code' and prefix_typo('claude_code') is None
    assert prefix_typo('openai') is None and prefix_typo('my-vendor') is None
    assert resolve('openai/gpt-5.6').backend == 'remote'      # a vendor still falls through


# -- changing the turn model -----------------------------------------------------------

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
    b.lock.acquire()
    try:
        with pytest.raises(RuntimeError, match='while the assistant is working'):
            b.set_model('gemma-12b')
    finally: b.lock.release()


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

def test_the_claude_code_transport_loads_without_rearranging_toolslm():
    """The shim writes into `sys.modules`, which is a process-wide edit to another package, so it
    must happen when the transport is loaded and not when this library is imported -- importing
    ramabana to read one constant rearranged `toolslm` for every other consumer in the process.
    """
    ok, error = core._load_claude_transport()
    assert ok, error
    from fastllm.acomplete import api_registry
    assert api_registry.get('claude_code') is not None

    child('import sys, ramabana\n'
          "assert 'toolslm.funccall' not in sys.modules, 'importing ramabana installed the shim'\n")
    child('import ramabana.core as core\n'          # loading the transport installs it
          'ok, err = core._load_claude_transport()\nassert ok, err\n'
          'from toolslm.funccall import mk_ns\nimport fastllm.chat\n')
    child('import sys, ramabana.core as core\n'     # and so does reaching it through a model
          "core.resolve('claude_code/claude-sonnet-5')\n"
          "assert 'toolslm.funccall' in sys.modules\n")


def test_a_blocking_call_consumes_the_stream_only_transport():
    "FastLLM's Claude Code transport is stream-only, and `Agent.ask` is not."

    class Chat:
        def __call__(self, msg, stream=False, **kw):
            assert stream is True
            return iter(('hello ', 'from claude'))

    be = RishiBackend(ModelSpec('claude', 'remote', 'claude_code/claude-sonnet-4-6'))
    be.chat, be._tried = Chat(), True
    assert be._send('hi') == 'hello from claude'


def test_the_tools_travel_in_the_system_prompt_when_the_wire_is_closed(monkeypatch):
    "Managed Claude Code closes MCP tools; schemas go in the system prompt with `tool_mode='tags'`."
    from fastllm.acomplete import api_registry

    def search_code(query: str) -> str:
        "Search the codebase."
        return ''

    spec = ModelSpec('claude', 'remote', 'claude_code/claude-sonnet-5', 200_000)
    # Both halves are stated. Whether this machine carries an organisation's managed config is
    # not the harness's business, and on one that does the unmanaged half read as a code failure.
    monkeypatch.setattr(core, '_managed_claude_mcp', lambda: False)
    assert core.claude_tags(spec.model_id) is False            # unmanaged: the native path
    assert RishiBackend(spec)._runtime_kw().get('tool_mode') is None

    monkeypatch.setattr(core, '_managed_claude_mcp', lambda: True)
    assert core.claude_tags(spec.model_id) is True
    be = RishiBackend(spec, sp='You are Ramabana.', tools=[search_code])
    assert be._runtime_kw()['tool_mode'] == 'tags'
    kw = be.start()._kw()
    assert 'tools' not in kw                                   # the channel policy closed
    assert '<tools>' in kw['system'] and '"search_code"' in kw['system']

    core._load_claude_transport()                              # and the strip keeps the tools now
    payload = api_registry['claude_code'].mk_payload([], 'claude-sonnet-5', system=kw['system'])
    assert payload['options'].mcp_servers == {}
    assert payload['options'].strict_mcp_config is False
    assert '<tools>' in payload['options'].system_prompt
    assert core.claude_tags('openai/gpt-5.6') is False          # not Claude Code: native as before


def test_a_tag_tool_call_comes_back_as_a_real_tool_call():
    "The reply is text either way; what changed is that rishi now reads the calls out of it."
    from aidialog.msg_parts import Msg, Part, PartType
    import rishi.remote as remote

    class Comp:
        tool_calls, finish_reason, model, usage = None, 'stop', 'claude-sonnet-5', None
        message = Msg(role='assistant', content=[Part(
            type=PartType.text,
            text='Looking now.\n<tool_call>\n{"name":"search_code","arguments":{"query":"rrf"}}\n</tool_call>')])

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
