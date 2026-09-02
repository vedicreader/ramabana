"""The memo every probe about this machine shares, and the seam an application fills.

Two faults behind this file. `Completer._prompt` reached `self.a.ws.agent_memory_context(...)`;
nothing in Ramabana ever sets `Agent.ws`, so the call raised `AttributeError` into a bare `except`
and a person's pinned notes never reached a completion prompt anywhere. And three copies of the
same idea existed at once: `_oai_cache` and `_copilot_cat` as bare module tuples here, and a fuller
`probed` in Leela with disk persistence and a background refresh.
"""
import json
import tempfile
import time
from pathlib import Path

import pytest

from ramabana import core
from ramabana.agent import Agent, Completer
from ramabana.core import (API_KEYS, CUSTOM, MODELS, delete_model, forget_probes, load_models,
                           probe_path, probed, runtime_detail, runtime_remedy, save_model,
                           saved_models, unregister_model)
from ramabana.tools import NullHost


@pytest.fixture
def probes(tmp_path):
    forget_probes()
    yield tmp_path
    forget_probes()


def test_the_first_caller_pays_and_every_caller_behind_it_is_served(probes):
    calls = []
    def fn():
        calls.append(1)
        return f'answer {len(calls)}'
    assert probed('k', fn, dir=probes) == 'answer 1'
    assert probed('k', fn, dir=probes) == 'answer 1'
    assert len(calls) == 1


def test_a_kept_answer_survives_the_process_that_found_it(probes):
    assert probed('k', lambda: 'found', dir=probes) == 'found'
    assert json.loads(probe_path('k', dir=probes).read_text())['value'] == 'found'
    forget_probes()                       # a fresh process, with the file still there
    assert probed('k', lambda: 'asked again', dir=probes) == 'found'


def test_a_stale_answer_is_served_now_and_refreshed_behind_the_caller(probes):
    calls = []
    def fn():
        calls.append(1)
        return f'answer {len(calls)}'
    assert probed('k', fn, dir=probes) == 'answer 1'
    assert probed('k', fn, ttl=0, dir=probes) == 'answer 1', 'the caller waits for nothing'
    for _ in range(400):
        if len(calls) > 1: break
        time.sleep(.01)
    assert len(calls) == 2
    assert probed('k', fn, dir=probes) == 'answer 2'


def test_an_answer_gathered_across_a_forget_is_discarded(probes):
    started, release = [], []
    def fn():
        started.append(1)
        while not release: time.sleep(.005)
        return 'about a machine that has changed'
    probed('k', lambda: 'first', dir=probes, disk=False)
    probed('k', fn, ttl=0, dir=probes, disk=False)
    for _ in range(400):
        if started: break
        time.sleep(.005)
    forget_probes()
    release.append(1)
    time.sleep(.1)
    assert probed('k', lambda: 'after the forget', dir=probes, disk=False) == 'after the forget'


def test_disk_false_is_the_same_memo_with_nothing_left_behind(probes):
    calls = []
    assert probed('k', lambda: calls.append(1) or 'v', dir=probes, disk=False) == 'v'
    assert probed('k', lambda: calls.append(1) or 'v', dir=probes, disk=False) == 'v'
    assert len(calls) == 1
    assert not probe_path('k', dir=probes).exists()


def test_a_probe_key_with_a_path_in_it_is_still_one_file_inside_its_own_directory(probes):
    p = probe_path('support:/usr/bin/python 3.12', dir=probes)
    assert p.parent == Path(probes)
    assert '/' not in p.name[1:]


def test_forget_probes_can_take_the_kept_answers_with_it(probes):
    probed('k', lambda: 'v', dir=probes)
    assert probe_path('k', dir=probes).exists()
    forget_probes(disk=True, dir=probes)
    assert not probe_path('k', dir=probes).exists()


def test_a_probe_whose_directory_cannot_be_written_still_answers(tmp_path):
    forget_probes()
    blocked = tmp_path/'a-file'
    blocked.write_text('not a directory')
    assert probed('k', lambda: 'v', dir=blocked/'under-a-file') == 'v'
    forget_probes()


def test_the_two_module_level_caches_are_gone():
    assert not hasattr(core, '_oai_cache')
    assert not hasattr(core, '_copilot_cat')


def test_the_openai_and_copilot_catalogues_go_through_the_one_memo(monkeypatch, probes):
    forget_probes()
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-not-a-real-key')
    calls = []
    monkeypatch.setattr(core, '_openai_ids', lambda: calls.append(1) or ['gpt-5', 'gpt-4.1'])
    assert core._openai_models() == ['gpt-5']
    assert core._openai_models(include_legacy=True) == ['gpt-4.1', 'gpt-5']
    assert len(calls) == 1, 'one listing serves both readings of it'
    monkeypatch.delenv('OPENAI_API_KEY')
    assert core._openai_models() == [], 'and no key is no models, whatever is memoized'


def test_a_runtime_says_why_it_cannot_be_reached_and_not_only_that_it_cannot():
    assert runtime_detail('mlx') == '', 'only a harness has a reason to give'
    assert runtime_detail('nosuch') == ''
    detail = runtime_detail('copilot')
    assert detail == '' or detail.startswith(('import rishi.copilot:', 'copilot_oauth'))
    assert 'rishi[nosuch]' in runtime_remedy('nosuch'), 'the remedy is still advice, not a reason'


def test_a_saved_alias_comes_back_after_the_process_that_made_it(tmp_path):
    p = tmp_path/'models.json'
    save_model({'name': 'saved-remote', 'model_id': 'anthropic/claude-sonnet-4-5',
                'runtime': 'remote', 'ctx': 200_000, 'base_url': 'https://example.invalid'}, path=p)
    unregister_model('saved-remote')
    assert 'saved-remote' not in CUSTOM
    assert [r['name'] for r in load_models(path=p)] == ['saved-remote']
    assert CUSTOM['saved-remote']['config']['base_url'] == 'https://example.invalid'
    assert delete_model('saved-remote', path=p) == 'saved-remote'
    assert saved_models(path=p) == []
    assert 'saved-remote' not in CUSTOM


def test_an_alias_file_that_cannot_be_read_is_an_empty_list(tmp_path):
    assert saved_models(path=tmp_path/'never-written.json') == []
    junk = tmp_path/'junk.json'
    junk.write_text('{')
    assert saved_models(path=junk) == []
    junk.write_text('{"name": "not a list"}')
    assert saved_models(path=junk) == []


@pytest.mark.parametrize('row,message', [
    ({'name': 'has spaces', 'model_id': 'x', 'runtime': 'remote'}, 'name must use'),
    ({'name': 'ok', 'model_id': 'x', 'runtime': 'nosuch'}, 'runtime must be one of'),
    ({'name': 'ok', 'model_id': 'x', 'runtime': 'remote', 'ctx': 10}, 'context must be'),
    ({'name': 'ok', 'model_id': 'x', 'runtime': 'litert', 'base_url': 'u'}, 'only to the remote runtime'),
])
def test_a_refused_alias_says_which_field_refused_it(tmp_path, row, message):
    with pytest.raises(ValueError, match=message):
        save_model(row, path=tmp_path/'models.json')


def test_a_built_in_name_cannot_be_taken_by_an_alias(tmp_path):
    name = next(n for n in MODELS if n not in CUSTOM)
    with pytest.raises(ValueError, match='built-in model name'):
        save_model({'name': name, 'model_id': 'x', 'runtime': 'remote'}, path=tmp_path/'models.json')


def test_an_api_key_is_never_among_the_fields_an_alias_keeps():
    assert 'api_key' not in API_KEYS
    assert 'api_key_env' in API_KEYS, 'the variable name is kept; the value stays in the environment'


def test_the_completer_asks_the_agent_rather_than_an_attribute_only_leela_set():
    class Embedder:
        host = NullHost()
        def memory_context(self, surface, max_chars=6000): return f'note for {surface}'
    prompt = Completer(Embedder())._prompt('x = 1', 5, 'python')
    assert '<user_memory>\nnote for completion\n</user_memory>' in prompt


def test_an_agent_with_no_vault_answers_nothing_and_the_prompt_says_nothing():
    class Bare:
        host = NullHost()
        memory_context = Agent.memory_context
    assert Agent.memory_context(None, 'completion') == ''
    assert '<user_memory>' not in Completer(Bare())._prompt('x = 1', 5, 'python')


def test_a_vault_that_raises_costs_a_note_and_never_the_completion():
    class Broken:
        host = NullHost()
        def memory_context(self, surface, max_chars=6000): raise RuntimeError('vault is shut')
    prompt = Completer(Broken())._prompt('x = 1', 5, 'python')
    assert '<user_memory>' not in prompt and '<before>' in prompt
