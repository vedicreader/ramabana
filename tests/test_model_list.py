"""`available_models` for a picker that opens at once: the sign-in check runs at most once a minute, the provider
lists stay on disk, the slow probes start together, and `ttl` keeps the whole answer.

abhyasa's Settings page waited 2.8 to 3.6 s for its first model list in each process, and 0.69 s for each later one.
"""
import time

import pytest

import ramabana.core as core
from ramabana.core import auth_status, available_models, forget_probes, probe_path, probed


@pytest.fixture
def machine(monkeypatch, tmp_path):
    "A machine with Claude Code, Copilot and ollama, whose probes are fakes that count their calls and take `slow` seconds."
    monkeypatch.setattr(core, 'PROBE_DIR', tmp_path)
    forget_probes()
    calls, slow = {}, {'s': 0.}
    def fake(name, value):
        def f(*a, **kw):
            calls[name] = calls.get(name, 0) + 1
            time.sleep(slow['s'])
            return value(*a) if callable(value) else value
        return f
    monkeypatch.setattr(core, 'runtime_available', lambda rt: rt in ('litert', 'claude', 'copilot', 'ollama', 'remote'))
    monkeypatch.setattr(core, '_ollama_models', fake('ollama', ['qwen3:4b']))
    monkeypatch.setattr(core, '_copilot_chat_models', fake('copilot', ['gpt-6-sol']))
    monkeypatch.setattr(core, 'auth_status', fake('auth', lambda: {v: {'available': v == 'openai', 'source': 'OPENAI_API_KEY'} for v in core.VENDORS}))
    monkeypatch.setattr(core, 'provider_models', fake('lists', lambda p, legacy=False: ['claude-opus-5-5'] if p == 'claude' else ['gpt-6-sol']))
    yield calls, slow
    forget_probes()


def test_no_ttl_asks_each_time(machine):
    calls, _ = machine
    first = available_models()
    assert available_models() == first
    assert calls['auth'] == 2 and calls['ollama'] == 2, 'without `ttl` nothing is kept, as before'


def test_a_second_call_within_ttl_asks_nothing(machine):
    calls, _ = machine
    rows = available_models(ttl=60)
    before = dict(calls)
    assert available_models(ttl=60) == rows
    assert calls == before


def test_a_caller_that_changes_a_row_changes_no_kept_row(machine):
    available_models(ttl=60)[0]['value'] = 'changed'
    assert available_models(ttl=60)[0]['value'] != 'changed'


def test_a_new_process_shows_the_rows_on_disk_at_once(machine):
    calls, slow = machine
    rows = available_models(ttl=60)
    assert probe_path('available-models-False').exists()
    forget_probes()   # a new process: nothing in memory, the file on disk
    slow['s'] = 1.
    t = time.monotonic()
    assert available_models(ttl=60) == rows
    assert time.monotonic() - t < .5, 'the rows on disk come back while the refresh runs behind'


def test_forget_probes_with_disk_removes_the_file(machine):
    available_models(ttl=60)
    forget_probes(disk=True)
    assert not probe_path('available-models-False').exists()


def test_forget_removes_a_file_written_to_another_folder(tmp_path, monkeypatch):
    "Leela forgets its probes with its own `dir`; the provider lists are on ramabana's."
    monkeypatch.setattr(core, 'PROBE_DIR', tmp_path/'ramabana')
    forget_probes()
    probed('lists', lambda: [1])
    assert probe_path('lists').exists()
    forget_probes(disk=True, dir=tmp_path/'leela')
    assert not probe_path('lists').exists()


def test_the_slow_probes_run_at_the_same_time(machine):
    _, slow = machine
    slow['s'] = 1.
    t = time.monotonic()
    available_models()
    assert time.monotonic() - t < 1.5, 'eight probes of 1 s each start together'


def test_each_row_says_whether_it_is_local_and_its_model_id(machine):
    rows = {r['value']: r for r in available_models()}
    assert rows['gemma-e4b']['local'] and rows['gemma-e4b']['model_id']
    assert not rows['claude/claude-opus-5-5']['local'] and rows['claude/claude-opus-5-5']['model_id'] == 'claude-opus-5-5'
    assert rows['openai/gpt-6-sol']['model_id'] == core.resolve('openai/gpt-6-sol').model_id
    assert all({'value', 'label', 'provider', 'source', 'local', 'model_id'} <= set(r) for r in rows.values())


def test_the_claude_sign_in_is_asked_at_most_once_a_minute(monkeypatch):
    forget_probes()
    runs = []
    class Done: returncode, stdout = 0, '{"loggedIn": true}'
    monkeypatch.setattr(core.shutil, 'which', lambda b: f'/bin/{b}')
    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **kw: runs.append(a) or Done())
    assert core._claude_login() and core._claude_login()
    assert len(runs) == 1
    forget_probes()


def test_auth_status_still_follows_the_environment(monkeypatch):
    "Only the Claude Code sign-in is kept; a key set in the environment shows at once."
    monkeypatch.setattr(core, '_claude_login', lambda: False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert not auth_status()['openai']['available']
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    assert auth_status()['openai']['available']
