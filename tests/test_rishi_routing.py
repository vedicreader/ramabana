from ramabana.runtime import RishiBackend, make_backend
import subprocess
import sys

import pytest

from ramabana.core import DEFAULT_POLICY, LOCAL, ONESHOT_JOBS, Routing, resolve


def test_litert_model_is_the_configurable_default():
    assert LOCAL['gemma-e4b'] == 'litert-community/gemma-4-E4B-it-litert-lm'
    assert DEFAULT_POLICY['oneshot'] == 'gemma-e4b'
    assert resolve('gemma-e4b').runtime == 'litert'


def test_every_cheap_job_takes_the_one_shot_model():
    "The default is unchanged; what changed is that it is now named once instead of three times."
    r = Routing(turn='gpt-mini')
    for job in ONESHOT_JOBS: assert r.name_for(job) == 'gemma-e4b', job
    assert r.name_for('turn') == 'gpt-mini'
    assert r.name_for('subagent') == 'gemma-e4b'


def test_pointing_the_one_shot_model_somewhere_moves_every_cheap_job():
    r = Routing(turn='gpt-mini')
    r.policy['oneshot'] = 'gpt-sol'
    for job in ONESHOT_JOBS: assert r.name_for(job) == 'gpt-sol', job
    r.policy['summary'] = 'gpt'                       # one job may still be singled out
    assert r.name_for('summary') == 'gpt'
    assert r.name_for('classify') == 'gpt-sol'


def test_a_cheap_job_whose_model_is_not_installed_runs_somewhere_else(hide_runtime):
    """`resolve` raises for a runtime whose dependency is missing, and the caller swallowed it --
    so on a machine without LiteRT every one-shot silently returned ''."""
    hide_runtime('mlx')
    r = Routing(turn='gpt-mini')
    r.policy['oneshot'] = 'mlx/not-installed-here'
    with pytest.raises(Exception): r.spec('oneshot', fallback=False)
    assert r.spec('classify').name == 'gpt-mini'      # the turn model, which is by definition here
    assert 'unavailable' in r.notes['classify']


def test_the_turn_model_never_falls_back(hide_runtime):
    "The user chose it. Running something else without saying so is worse than failing."
    hide_runtime('mlx')
    r = Routing(turn='mlx/not-installed-here')
    with pytest.raises(Exception): r.spec('turn')


def test_claude_code_transport_loads_through_fastllm_plugin(monkeypatch):
    import ramabana.core as core
    from fastllm.acomplete import api_registry
    ok, error = core._load_claude_transport()
    assert ok, error
    transport = api_registry.get('claude_code')
    assert transport is not None
    monkeypatch.setattr(core, '_managed_claude_mcp', lambda: True)
    payload = transport.mk_payload([], 'claude-sonnet-5')
    assert payload['options'].strict_mcp_config is False
    assert payload['options'].mcp_servers == {}


def test_importing_ramabana_does_not_rearrange_toolslm():
    """The shim writes into `sys.modules`, which is a process-wide edit to another package.

    Doing it as a side effect of `import ramabana.core` meant importing this library to read
    one constant rearranged `toolslm` for every other consumer in the interpreter.
    """
    code = ('import sys, ramabana\n'
            "assert 'toolslm.funccall' not in sys.modules, 'importing ramabana installed the shim'\n")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_loading_the_claude_transport_installs_the_funccall_shim():
    "`fastllm.chat` is the only thing that needs it, and the Claude Code transport is what imports it."
    code = ('import ramabana.core as core\n'
            'ok, err = core._load_claude_transport()\n'
            'assert ok, err\n'
            'from toolslm.funccall import mk_ns\n'
            'import fastllm.chat\n')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_resolving_a_claude_code_model_installs_it_too():
    "Nothing can reach the transport without first resolving the model that uses it."
    code = ('import sys, ramabana.core as core\n'
            "core.resolve('claude_code/claude-sonnet-5')\n"
            "assert 'toolslm.funccall' in sys.modules\n")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_blocking_agent_call_consumes_claude_code_stream():
    from ramabana.core import ModelSpec

    class Chat:
        def __call__(self, msg, stream=False, **kw):
            assert stream is True
            return iter(('hello ', 'from claude'))

    backend = RishiBackend(ModelSpec('claude', 'remote', 'claude_code/claude-sonnet-4-6'))
    backend.chat, backend._tried = Chat(), True
    assert backend._send('hi') == 'hello from claude'


def test_uninstalled_optional_runtime_is_hidden_and_blocked(monkeypatch):
    import ramabana.core as core
    real = core.importlib.util.find_spec
    monkeypatch.setattr(core.importlib.util, 'find_spec',
                        lambda name: None if name == 'mlx_lm' else real(name))
    assert not core.runtime_available('mlx')
    assert all(row['provider'] != 'mlx' for row in core.available_models())
    with pytest.raises(RuntimeError, match=r'install rishi\[mlx\]'):
        core.resolve('mlx/mlx-community/example')


def test_saved_remote_runtime_options_reach_rishi(monkeypatch):
    from ramabana.core import register_model
    spec=register_model('private-api','openai/private-model','remote',64_000,
                        base_url='https://api.example.test/v1',api_key_env='PRIVATE_API_KEY')
    monkeypatch.setenv('PRIVATE_API_KEY','secret')
    be=RishiBackend(spec)
    assert be._runtime_kw()['base_url'].endswith('/v1')
    assert be._runtime_kw()['api_key']=='secret'


def test_litert_gpu_backend_can_be_selected_globally(monkeypatch):
    """The accelerator goes to rishi as `backend=`, the parameter it builds the engine from.
    Inside `eng_kw` it reached that engine twice and no litert model loaded at all."""
    from litert_lm import Backend as LB
    monkeypatch.setenv('RAMABANA_LITERT_BACKEND', 'gpu')
    kw = RishiBackend(resolve('gemma-e4b'))._runtime_kw()
    assert isinstance(kw['backend'], LB.GPU) and 'backend' not in kw['eng_kw']

    kw = RishiBackend(resolve('gemma-e4b'), eng_kw=dict(backend=LB.CPU()))._runtime_kw()
    assert isinstance(kw['eng_kw']['backend'], LB.CPU) and 'backend' not in kw  # explicit wins


def test_unknown_litert_backend_is_rejected(monkeypatch):
    monkeypatch.setenv('RAMABANA_LITERT_BACKEND', 'cuda')
    with pytest.raises(ValueError, match='use cpu or gpu'):
        RishiBackend(resolve('gemma-e4b'))._runtime_kw()


def test_every_model_uses_the_rishi_adapter():
    for name in ('gemma-e2b', 'gemma-e4b', 'sonnet'):
        assert isinstance(make_backend(resolve(name)), RishiBackend)


def test_ramabana_does_not_import_leela():
    import ramabana
    bad=[]
    for p in ramabana.__path__:
        from pathlib import Path
        for f in Path(p).glob('*.py'):
            for n,line in enumerate(f.read_text().splitlines(),1):
                if line.startswith(('from leela','import leela')): bad.append(f'{f.name}:{n}')
    assert not bad


def test_a_short_local_name_is_checked_for_its_runtime_like_a_long_one():
    """`resolve('mlx/...')` always refused a runtime that is not installed; `resolve('qwen-4b')`
    did not, so a job routed to it got a spec, built a backend, and failed at `start()`."""
    from ramabana.core import runtime_available
    for short, long in (('qwen-4b', 'mlx/mlx-community/Qwen3.5-4B-MLX-4bit'),
                        ('gemma-e4b', 'litert/litert-community/gemma-4-E4B-it-litert-lm')):
        runtime = resolve.__globals__['MODELS'][short][0]
        if runtime_available(runtime):
            assert resolve(short).runtime == runtime
            continue
        with pytest.raises(RuntimeError, match='unavailable'): resolve(short)
        with pytest.raises(RuntimeError, match='unavailable'): resolve(long)


def test_managed_mcp_sends_the_tools_in_the_system_prompt_instead(monkeypatch):
    """An enterprise-managed Claude Code forbids every dynamic MCP server, and MCP is how that
    transport declares tools -- so stripping them left the model with no tools at all."""
    import ramabana.core as core
    from ramabana.core import ModelSpec
    from fastllm.acomplete import api_registry

    def search_code(query: str) -> str:
        "Search the codebase."
        return ''

    spec = ModelSpec('claude', 'remote', 'claude_code/claude-sonnet-5', 200_000)
    # Both halves are stated, because whether this machine carries a managed config is not the
    # harness's business: on one that does, the unmanaged half read as a failure of the code.
    monkeypatch.setattr(core, '_managed_claude_mcp', lambda: False)
    assert core.claude_tags(spec.model_id) is False           # unmanaged: the native path
    assert RishiBackend(spec)._runtime_kw().get('tool_mode') is None

    monkeypatch.setattr(core, '_managed_claude_mcp', lambda: True)
    assert core.claude_tags(spec.model_id) is True
    backend = RishiBackend(spec, sp='You are Ramabana.', tools=[search_code])
    assert backend._runtime_kw()['tool_mode'] == 'tags'

    chat = backend.start()
    kw = chat._kw()
    assert 'tools' not in kw                                  # the channel policy closed
    assert '<tools>' in kw['system'] and '"search_code"' in kw['system']

    # and the strip that policy requires no longer takes the tools with it
    core._load_claude_transport()
    payload = api_registry['claude_code'].mk_payload([], 'claude-sonnet-5', system=kw['system'])
    assert payload['options'].mcp_servers == {}
    assert '<tools>' in payload['options'].system_prompt

    # a model that is not Claude Code keeps its native tool calling
    assert core.claude_tags('openai/gpt-5.6') is False


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
