from ramabana.runtime import RishiBackend, make_backend
import subprocess
import sys

import pytest

from ramabana.core import DEFAULT_POLICY, LOCAL, resolve


def test_litert_model_is_the_configurable_default():
    assert LOCAL['gemma-e4b'] == 'litert-community/gemma-4-E4B-it-litert-lm'
    assert DEFAULT_POLICY['completion'] == 'gemma-e4b'
    assert resolve('gemma-e4b').runtime == 'litert'


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


def test_fastllm_sees_funccall_compatibility_module_process_wide():
    code = 'import ramabana; from toolslm.funccall import mk_ns; import fastllm.chat'
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
    from litert_lm import Backend as LB
    monkeypatch.setenv('RAMABANA_LITERT_BACKEND', 'gpu')
    backend = RishiBackend(resolve('gemma-e4b'))._runtime_kw()['eng_kw']['backend']
    assert isinstance(backend, LB.GPU)


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
