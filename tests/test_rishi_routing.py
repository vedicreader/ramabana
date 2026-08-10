from ramabana.runtime import RishiBackend, make_backend
from ramabana.core import DEFAULT_POLICY, MLX, resolve


def test_mlx_coding_models_are_configurable_defaults():
    assert MLX['qwen-4b'] == 'mlx-community/Qwen3.5-4B-MLX-4bit'
    assert MLX['mini-coder-4b'] == 'mlx-community/mini-coder-4b-OptiQ-4bit'
    assert DEFAULT_POLICY['completion'] == 'mini-coder-4b'
    assert resolve('qwen-4b').runtime == resolve('mini-coder-4b').runtime == 'mlx'


def test_saved_remote_runtime_options_reach_rishi(monkeypatch):
    from ramabana.core import register_model
    spec=register_model('private-api','openai/private-model','remote',64_000,
                        base_url='https://api.example.test/v1',api_key_env='PRIVATE_API_KEY')
    monkeypatch.setenv('PRIVATE_API_KEY','secret')
    be=RishiBackend(spec)
    assert be._runtime_kw()['base_url'].endswith('/v1')
    assert be._runtime_kw()['api_key']=='secret'


def test_every_model_uses_the_rishi_adapter():
    for name in ('qwen-4b', 'gemma-e4b', 'llama-qwen-0.6b', 'sonnet'):
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
