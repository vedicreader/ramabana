"Azure OpenAI, and any hosted model config.toml defines, for a machine with no Claude Code and no Codex. Nothing here calls the network."
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
    monkeypatch.setenv('AZURE_OPENAI_DEPLOYMENTS', 'gpt-5.4,gpt-5.4-mini')


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
           '[model."gpt-5.4"]\nmodel_id = "gpt-5.4"\nbase_url = "https://x"\n[azure]\ndeployments = "not-a-list"\n')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        with pytest.raises(KeyError): resolve('odd')
        bad = core.model_problems()
    assert any('half' in b and 'no model_id' in b for b in bad) and any('odd' in b and 'unknown runtime' in b for b in bad)
    assert any('gpt-5.4' in b and 'built-in' in b for b in bad), bad
    assert resolve('gpt-5.4').model_id == 'openai/gpt-5.4', 'a built-in name is never taken over'
    assert any('azure.deployments' in str(x.message) for x in w) and core.azure_deployments() == []


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


def test_azure_deployments_appear_everywhere_a_model_is_listed(azure):
    assert auth_status()['azure'] == {'available': True, 'source': 'AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY'}
    rows = [r for r in available_models() if r['provider'] == 'azure']
    assert [r['value'] for r in rows] == ['azure/gpt-5.4', 'azure/gpt-5.4-mini']
    spec = resolve('azure/gpt-5.4')
    assert (spec.runtime, spec.model_id, spec.config) == ('remote', 'gpt-5.4', {'base_url': AZ, 'api_key_env': 'AZURE_OPENAI_API_KEY', 'api_name': 'openai'})
    assert not spec.note and spec.ctx > 128_000, 'a deployment named for its model gets that model window'
    odd = resolve('azure/prod-chat')
    assert odd.ctx == 128_000 and 'max_input_tokens under [model."azure/prod-chat"]' in odd.note
    _write('[model."azure/prod-chat"]\nmax_input_tokens = 64000\n')
    assert (resolve('azure/prod-chat').ctx, resolve('azure/prod-chat').note) == (64000, '')


def test_an_azure_model_without_an_endpoint_or_key_says_what_is_missing(monkeypatch):
    assert missing_key(resolve('azure/gpt-5.4')) == 'AZURE_OPENAI_ENDPOINT'
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    assert missing_key(resolve('azure/gpt-5.4')) == 'AZURE_OPENAI_API_KEY' and not auth_status()['azure']['available']
    _write('[azure]\napi_key_env = "MY_AZ_KEY"\n')
    monkeypatch.setenv('MY_AZ_KEY', 'k')
    assert missing_key(resolve('azure/gpt-5.4')) == '' and auth_status()['azure']['available']


def test_with_only_azure_every_job_moves_there_with_one_note(bare, azure):
    r = Routing()
    assert r.turn == 'azure/gpt-5.4'
    assert {j: r.name_for(j) for j in JOBS} == dict(turn='azure/gpt-5.4', oneshot='azure/gpt-5.4-mini', inline='azure/gpt-5.4-mini', completion='azure/gpt-5.4-mini',
                                                     classify='azure/gpt-5.4-mini', summary='azure/gpt-5.4', subagent='azure/gpt-5.4')
    assert len(r.news) == 1 and 'cannot run here' in r.news[0] and 'azure/gpt-5.4-mini' in r.news[0], r.news
    assert 'claude' in r.notes['turn'] and 'Codex' in r.notes['summary']
    assert all(r.spec(j).config['base_url'] == AZ for j in JOBS)
    r.set('qwen-4b')
    assert r.name_for('summary') == 'qwen-4b', 'a rehomed job is not chosen, so it follows a local turn'


def test_a_chosen_azure_turn_takes_the_jobs_and_a_chosen_job_stays(bare, monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')
    _write('[jobs]\nturn = "azure/big"\nclassify = "azure/tiny"\n')
    r = Routing()
    assert (r.turn, r.name_for('summary'), r.name_for('completion'), r.name_for('classify')) == ('azure/big', 'azure/big', 'azure/big', 'azure/tiny')


def test_azure_without_deployments_says_how_to_name_one(bare, monkeypatch):
    monkeypatch.setenv('AZURE_OPENAI_ENDPOINT', 'https://res.openai.azure.com')
    monkeypatch.setenv('AZURE_OPENAI_API_KEY', 'k')
    r = Routing()
    assert r.turn == core.DFLT_TURN and core.AZURE_UNNAMED in r.news
    assert 'AZURE_OPENAI_DEPLOYMENTS' in core.reachable_hint()


def test_where_claude_code_runs_azure_only_catches_what_falls(azure, monkeypatch):
    monkeypatch.setattr(core, '_claude_available', lambda: True)
    monkeypatch.setattr(core, '_codex_login', lambda: False)
    r = Routing()
    assert (r.turn, r.name_for('completion'), r.name_for('summary')) == (core.DFLT_TURN, core.DFLT_SMALL, 'azure/gpt-5.4')
    alts = r.alternatives('completion')
    assert {'azure/gpt-5.4', 'azure/gpt-5.4-mini'} <= set(alts) and alts[-1] == core.DFLT_FALLBACK, alts


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


def test_a_stock_hosted_turn_with_nothing_configured_moves_no_job(monkeypatch):
    "CI has Claude Code and no Codex: `Routing(turn='sonnet')` moved the summary job onto sonnet, though no hosted model was configured."
    monkeypatch.setattr(core, '_claude_available', lambda: True)
    monkeypatch.setattr(core, '_codex_login', lambda: False)
    r = Routing(turn='sonnet')
    assert (r.name_for('summary'), r.news) == ('gpt-6-luna', [])
