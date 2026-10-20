"Azure OpenAI, AWS Bedrock and any hosted model config.toml defines, and the setup step when nothing runs. Nothing here calls the network."
import os, subprocess, sys, warnings
import pytest
from ramabana import core
from ramabana.agent import Agent
from ramabana.core import JOBS, Routing, available_models, auth_status, missing_key, model_note, resolve
from ramabana.runtime import RishiBackend
from ramabana.setup import config_path, config_show
from ramabana.testing import MemHost

AZ = 'https://res.openai.azure.com/openai/v1'

def _write(text): config_path().write_text(text); return config_path()

@pytest.fixture
def bare(monkeypatch):
    "No Claude Code, no Codex login, no model chosen by env var."
    monkeypatch.setattr(core, '_claude_available', lambda: False)
    monkeypatch.setattr(core, '_codex_login', lambda: False)
    for p in ('RAMABANA_', 'LEELA_'):
        for j in ('', *(f'_{j.upper()}' for j in JOBS)): monkeypatch.delenv(f'{p}MODEL{j}', raising=False)

@pytest.fixture
def azure(monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com/')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')


@pytest.mark.parametrize('url', ['https://res.openai.azure.com', 'https://res.openai.azure.com/', 'res.openai.azure.com',
                                 'https://res.openai.azure.com/openai/v1/', 'https://res.openai.azure.com/openai/deployments/x/chat/completions?api-version=2024-10-21'])
def test_every_shape_of_endpoint_becomes_the_v1_base(url):
    assert core.azure_base(url) == AZ
    assert core.azure_base('https://r.cognitiveservices.azure.com/') == 'https://r.cognitiveservices.azure.com/openai/v1'
    assert core.azure_base('https://apim.azure-api.net/team/openai') == 'https://apim.azure-api.net/team/openai/v1'


def test_a_config_toml_definition_is_a_model_the_cli_can_name(monkeypatch):
    "`[jobs] turn = \"az-big\"` raised 'unknown model': the CLI never loaded a model alias, and config.toml could not define one."
    _write('[jobs]\nturn = "az-big"\n[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com"\nmax_input_tokens = 200000\n')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')
    r = Routing()
    spec = r.spec('turn')
    assert (r.turn, spec.runtime, spec.model_id, spec.ctx) == ('az-big', 'remote', 'gpt-5.4', 200000)
    assert spec.config == {'api_name': 'openai', 'api_key_env': 'AZURE_OPENAI_API_KEY', 'base_url': 'https://res.openai.azure.com'}
    kw = RishiBackend(spec)._runtime_kw()
    assert (kw['api_key'], kw['base_url'], kw['api_name']) == ('k', 'https://res.openai.azure.com', 'openai') and 'api_key_env' not in kw
    assert 'Azure OpenAI' in model_note(spec) and 'az-big' in [x['value'] for x in available_models()]
    assert 'model."az-big".model_id = "gpt-5.4"' in config_show()


def test_a_definition_without_its_key_says_which_env_var_it_needs(monkeypatch, tmp_path):
    _write('[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com"\n')
    a = Agent(MemHost(), model='az-big', cfg=tmp_path/'cfg', extensions=False, subagents=False)
    assert a.model.name == 'az-big' and missing_key(a.model) == 'AZURE_OPENAI_API_KEY'
    out = a.ask('hello')
    assert 'needs AZURE_OPENAI_API_KEY' in out, out


def test_entries_that_cannot_define_a_model_warn_and_never_raise():
    _write('[model."half"]\nbase_url = "https://x"\n[model."odd"]\nmodel_id = "m"\nruntime = "nosuch"\n'
           '[model."gpt-5.4"]\nmodel_id = "gpt-5.4"\nbase_url = "https://x"\n[azure]\ndeployments = ["d"]\n')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        with pytest.raises(KeyError): resolve('odd')
        bad = core.model_problems()
    assert any('half' in b and 'no model_id' in b for b in bad) and any('odd' in b and 'unknown runtime' in b for b in bad)
    assert any('gpt-5.4' in b and 'built-in' in b for b in bad), bad
    assert resolve('gpt-5.4').model_id == 'openai/gpt-5.4', 'a built-in name is never taken over'
    assert any('no longer choose models' in str(x.message) for x in w), 'a key 0.2.46 read says what to do instead'


def test_config_toml_wins_a_name_a_saved_alias_also_defines(tmp_path):
    p = tmp_path/'models.json'
    core.save_model({'name': 'mine', 'model_id': 'openai/gpt-4.1', 'runtime': 'remote'}, path=p)
    _write('[model."mine"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com"\n')
    assert resolve('mine').model_id == 'gpt-5.4'
    core.load_models(path=p)
    assert resolve('mine').model_id == 'gpt-5.4', 'an app loading its own file does not take the name back'
    with pytest.raises(ValueError, match='defined in'): core.save_model({'name': 'mine', 'model_id': 'x', 'runtime': 'remote'}, path=p)
    _write('')
    with pytest.raises(KeyError): resolve('mine')   # gone from config.toml, and the saved row is in another app's file


def test_ramabanas_own_saved_aliases_load_without_a_call():
    core.save_model({'name': 'saved-az', 'model_id': 'gpt-5.4', 'runtime': 'remote', 'base_url': AZ, 'api_key_env': 'AZURE_OPENAI_API_KEY', 'api_name': 'openai'})
    core.unregister_model('saved-az'); core._SYNC['key'] = None   # as a fresh process finds it
    assert resolve('saved-az').config['base_url'] == AZ


def test_an_azure_model_without_an_endpoint_or_key_says_what_is_missing(monkeypatch):
    assert missing_key(resolve('azure/gpt-5.4')) == 'AZURE_OPENAI_ENDPOINT'
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    assert missing_key(resolve('azure/gpt-5.4')) == 'AZURE_OPENAI_API_KEY' and not auth_status()['azure']['available']
    _write('[azure]\napi_key_env = "MY_AZ_KEY"\n')
    monkeypatch.setenv('MY_AZ_KEY', 'k')
    assert missing_key(resolve('azure/gpt-5.4')) == '' and auth_status()['azure']['available']


def test_a_lent_chat_keeps_the_endpoint(azure, tmp_path, monkeypatch):
    "`lend_model` built `Chat(model_id)` alone, so a host's own chat on an Azure model went to OpenAI."
    seen = {}
    import rishi
    monkeypatch.setattr(rishi, 'Chat', lambda *a, **kw: seen.update(kw) or object())
    class H(MemHost): mk_chat = None
    a = Agent(H(), model='azure/gpt-5.4', cfg=tmp_path/'cfg', extensions=False, subagents=False)
    a.lend_model(); a.host.mk_chat('azure/gpt-5.4')
    assert (seen['base_url'], seen['api_key'], seen['api_name']) == (AZ, 'k', 'openai')


def test_the_cli_process_resolves_a_config_toml_model(tmp_path):
    "A fresh `python` with only config.toml and the env: the path `ramabana` and dhrona's runs take."
    cfg = tmp_path/'config.toml'
    cfg.write_text('[jobs]\nturn = "az-big"\n[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com"\n')
    env = {**os.environ, 'RAMABANA_CONFIG': str(cfg), 'AZURE_OPENAI_API_KEY': 'k', 'HOME': str(tmp_path)}
    env.pop('RAMABANA_MODEL', None); env.pop('LEELA_MODEL', None)
    code = 'from ramabana.core import Routing; s = Routing().spec("turn"); print(s.name, s.model_id, s.config["base_url"])'
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=120)
    assert out.stdout.split() == ['az-big', 'gpt-5.4', 'https://res.openai.azure.com'], out.stderr




def test_azure_in_the_environment_chooses_nothing(bare, azure):
    "0.2.46 moved every job onto Azure deployments by itself; a provider is only ever used where a person names it."
    r = Routing()
    assert r.turn == core.DFLT_TURN and r.news == [] and not any(x['provider'] == 'azure' for x in available_models())
    assert auth_status()['azure']['available'] and core.needs_setup(r)
    _write('[jobs]\nturn = "azure/gpt-5.4"\n')
    r = Routing()
    assert r.spec('turn').config['base_url'] == AZ and not core.needs_setup(r)
    spec = resolve('azure/gpt-5.4')
    assert (spec.runtime, spec.model_id, spec.config) == ('remote', 'gpt-5.4', {'base_url': AZ, 'api_key_env': 'AZURE_OPENAI_API_KEY', 'api_name': 'openai'})
    assert not spec.note and spec.ctx > 128_000, 'a deployment named for its model gets that model window'
    assert 'max_input_tokens under [model."azure/prod-chat"]' in resolve('azure/prod-chat').note


def test_with_nothing_set_up_the_guide_lists_every_provider_and_job(bare, monkeypatch, tmp_path):
    for k in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK'): monkeypatch.delenv(k, raising=False)
    g = core.setup_guide()
    for label in ('OpenAI API', 'Azure OpenAI', 'AWS Bedrock', 'Anthropic API', 'Gemini API', 'OpenRouter', 'Claude Code', 'Codex', 'On this machine'): assert label in g, label
    assert 'cannot run here' in g and 'ramabana setup' in g and 'turn        claude-opus-5-5' in g and 'default' in g
    assert 'image' in g and 'OPENAI_API_KEY' in g, 'the image job says what it lacks'
    a = Agent(MemHost(), cfg=tmp_path/'cfg', extensions=False, subagents=False)
    assert 'ramabana setup' in a.ask('hello')


def test_a_missing_key_turn_points_at_setup(tmp_path, monkeypatch):
    _write('[model."az-big"]\nmodel_id = "gpt-5.4"\nbase_url = "https://res.openai.azure.com"\n')
    a = Agent(MemHost(), model='az-big', cfg=tmp_path/'cfg', extensions=False, subagents=False)
    out = a.ask('hello')
    assert 'needs AZURE_OPENAI_API_KEY' in out and 'ramabana setup' in out, out


def test_a_bedrock_mantle_definition_resolves_with_its_window(monkeypatch):
    monkeypatch.setenv('AWS_BEARER_TOKEN_BEDROCK', 'k')
    _write('[model."bedrock-gpt"]\nmodel_id = "openai.gpt-5.4"\nbase_url = "https://bedrock-mantle.us-east-1.api.aws/v1"\napi_key_env = "AWS_BEARER_TOKEN_BEDROCK"\napi_name = "openai"\n')
    spec = resolve('bedrock-gpt')
    from fastllm.types import get_model_info
    win = get_model_info('openai.gpt-5.4', 'bedrock_mantle')['max_input_tokens']   # fastllm's Bedrock table, not a number of ours
    assert (spec.runtime, spec.model_id, spec.ctx, spec.note) == ('remote', 'openai.gpt-5.4', win, '')
    assert core.provider_ready('bedrock') and core.remote_models() == ['bedrock-gpt']
    assert 'no images endpoint' in (_write('[model."bedrock-gpt"]\nmodel_id = "openai.gpt-5.4"\nbase_url = "https://bedrock-mantle.us-east-1.api.aws/v1"\napi_key_env = "AWS_BEARER_TOKEN_BEDROCK"\n[jobs]\nimage = "bedrock-gpt"\n') and core.image_route())


def test_the_image_job_goes_where_config_toml_says(monkeypatch, tmp_path):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert 'OPENAI_API_KEY' in core.image_route()
    from ramabana.tools import tools_for
    from ramabana.testing import FullHost
    assert 'generate_image' not in [t.__name__ for t in tools_for(FullHost())], 'no image model, no tool'
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azk')
    _write('[model."az-image"]\nmodel_id = "gpt-image-1"\nbase_url = "https://res.openai.azure.com/openai/v1"\n[jobs]\nimage = "az-image"\n')
    assert core.image_route() == dict(name='az-image', base_url=AZ, api_key='azk', model='gpt-image-1')
    import httpx
    from base64 import b64encode
    sent = []
    def post(url, **kw):
        sent.append((url, kw['headers']['Authorization']))
        return httpx.Response(200, json={'data': [{'b64_json': b64encode(b'\x89PNG\r\n\x1a\n' + bytes(8)).decode()}]}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    h = FullHost()
    gen = next(t for t in tools_for(h) if t.__name__ == 'generate_image')
    (away := tmp_path/'cwd').mkdir()
    monkeypatch.chdir(away)
    out = gen('a kettle')
    assert sent == [(f'{AZ}/images/generations', 'Bearer azk')], 'Azure, never api.openai.com'
    from pathlib import Path
    assert Path(out).parent == h.root/'media' and not list(away.iterdir()), 'the host folder, never the working directory'


def test_setup_writes_a_provider_and_its_jobs_and_never_a_key(capsys):
    from ramabana.setup import setup_cli
    assert setup_cli(['--provider', 'bedrock', '--model-id', 'openai.gpt-5.4', '--region', 'eu-west-1', '--name', 'bed', '--jobs', 'turn,summary'], isatty=lambda: False) == 0
    import tomllib
    d = tomllib.loads(config_path().read_text())
    assert d['model']['bed'] == {'model_id': 'openai.gpt-5.4', 'base_url': 'https://bedrock-mantle.eu-west-1.api.aws/v1', 'api_key_env': 'AWS_BEARER_TOKEN_BEDROCK', 'api_name': 'openai'}
    assert d['jobs'] == {'turn': 'bed', 'summary': 'bed'}
    answers = iter(['4', 'gpt-5.4', 'https://res.openai.azure.com/', '', '', ''])
    assert setup_cli([], ask=lambda q: next(answers), isatty=lambda: True, out=lambda *a: None) == 0
    d = tomllib.loads(config_path().read_text())
    assert d['model']['azure-gpt-5.4']['base_url'] == AZ and d['jobs'] == {'turn': 'bed', 'summary': 'bed'}, 'no jobs question, and a named turn stays'
    assert setup_cli([], isatty=lambda: False) == 2 and 'Providers:' in capsys.readouterr().err, 'headless: the guide, no prompt'
    config_path().write_text('learning = [')
    assert setup_cli(['--provider', 'openai', '--model-id', 'gpt-5.4', '--jobs', 'turn'], isatty=lambda: False) == 1 and config_path().read_text() == 'learning = ['


def test_set_table_keeps_comments_and_quotes_a_model_name(tmp_path):
    from ramabana.setup import set_table
    import tomllib
    p = tmp_path/'c.toml'
    p.write_text('learning = false   # mine\n')
    set_table('jobs', {'turn': 'x'}, p); set_table('a/b c', {'model_id': 'm'}, p); set_table('jobs', {'turn': 'y', 'summary': 'z'}, p)
    assert '# mine' in p.read_text() and tomllib.loads(p.read_text()) == {'learning': False, 'jobs': {'turn': 'y', 'summary': 'z'}, 'model': {'a/b c': {'model_id': 'm'}}}


def test_the_video_job_goes_where_config_toml_says_and_refuses_what_makes_no_video(monkeypatch):
    "Leela's generate_video asked Gemini by name; it now asks the `video` job, and a model that cannot make video is refused."
    from ramabana.setup import load_config
    for k in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'RAMABANA_MODEL_VIDEO', 'LEELA_MODEL_VIDEO'): monkeypatch.delenv(k, raising=False)
    r = core.video_route()
    assert isinstance(r, str) and 'gemini/veo-3.0-generate-001 needs GEMINI_API_KEY' in r and '[jobs] video' in r
    monkeypatch.setenv('GOOGLE_API_KEY', 'gk')
    assert core.video_route() == dict(name=core.DFLT_VIDEO, api='gemini', base_url=core.GEMINI_BASE, api_key='gk', model='veo-3.0-generate-001')
    _write('[jobs]\nvideo = "gemini/gemini-2.5-flash"\n')
    assert load_config()[1] == [], '[jobs] video is a setting'
    assert 'gemini/gemini-2.5-flash makes no video' in core.video_route()
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'azk')
    _write('[model."az-sora"]\nmodel_id = "sora-2"\nbase_url = "https://res.openai.azure.com/openai/v1"\n[jobs]\nvideo = "az-sora"\n')
    assert core.video_route() == dict(name='az-sora', api='openai', base_url=AZ, api_key='azk', model='sora-2')
    monkeypatch.setenv('OPENAI_API_KEY', 'ok')
    assert core.video_route('openai/sora-2') == dict(name='openai/sora-2', api='openai', base_url='https://api.openai.com/v1', api_key='ok', model='sora-2'), 'a named model beats the job'
    monkeypatch.setenv('RAMABANA_MODEL_VIDEO', 'gemma-e4b')
    assert 'video comes only from a hosted API' in core.video_route()
    monkeypatch.setenv('OPENROUTER_API_KEY', 'k')
    assert 'no video endpoint' in core.video_route('openrouter/openai/sora-2')
    assert 'video ' in core.setup_guide()
