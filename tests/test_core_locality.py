"A model is local when it runs on this machine: an Ollama model counts only while its daemon is on a loopback host."
import sys

import pytest

from ramabana.core import ModelSpec, is_local

EMAIL = 'ada@example.com'
REMOTE, LOOPBACK = 'https://ollama.example.com', 'http://127.0.0.1:11434'


def ollama(host=None):
    return ModelSpec('ollama/qwen3:4b', 'ollama', 'qwen3:4b', 32_768, opts={'host': host} if host else {})


def test_an_ollama_model_is_local_only_where_its_daemon_is(monkeypatch):
    monkeypatch.delenv('OLLAMA_HOST', raising=False)
    assert ollama().local and is_local('ollama/qwen3:4b'), 'the default daemon is on this machine'
    monkeypatch.setenv('OLLAMA_HOST', REMOTE)
    assert not ollama().local and not is_local('ollama/qwen3:4b'), '$OLLAMA_HOST names a remote daemon'
    assert ollama(LOOPBACK).local, "the model's own host beats $OLLAMA_HOST"
    monkeypatch.setenv('OLLAMA_HOST', LOOPBACK)
    assert not ollama(REMOTE).local
    assert ModelSpec('m', 'litert', 'x').local and not ModelSpec('m', 'remote', 'openai/x').local


def test_a_loopback_or_wildcard_destination_is_this_machine_and_nothing_else_is(monkeypatch):
    monkeypatch.delenv('OLLAMA_HOST', raising=False)
    for host in ('localhost:11434', 'http://127.0.0.1:9999', '0.0.0.0:11434', 'http://0.0.0.0:11434', '[::]:11434', '[::1]:11434'):
        assert ollama(host).local, f'{host} reaches this machine'
    for host in ('https://ollama.example.com', '10.0.0.5:11434', '[2001:db8::1]:11434', 'unix:///tmp/ollama.sock'):
        assert not ollama(host).local, f'{host} is not known to be this machine'
    for env in ('0.0.0.0', '[::]:11434'):
        monkeypatch.setenv('OLLAMA_HOST', env)
        assert ollama().local and is_local('ollama/qwen3:4b'), env
    assert not ModelSpec('o', 'ollama', 'q', 1, opts={'client': object()}).local, 'a custom client has an unknown endpoint'


def test_an_ollama_model_is_hosted_when_the_endpoint_cannot_be_read(monkeypatch):
    monkeypatch.delenv('OLLAMA_HOST', raising=False)
    monkeypatch.setitem(sys.modules, 'rishi.ollama', None)
    assert not ollama().local
    assert ModelSpec('m', 'litert', 'x').local


def test_outgoing_text_to_a_remote_ollama_daemon_gets_the_hosted_policy(monkeypatch):
    from ramabana.guard import OutgoingRefused, outgoing
    monkeypatch.delenv('OLLAMA_HOST', raising=False)
    assert EMAIL in outgoing(f'email {EMAIL}', ollama(), mode='refuse')
    monkeypatch.setenv('OLLAMA_HOST', REMOTE)
    with pytest.raises(OutgoingRefused): outgoing(f'email {EMAIL}', ollama(), mode='refuse')
    assert outgoing(f'email {EMAIL}', ollama(), mode='redact') == 'email [EMAIL]'
    assert EMAIL in outgoing(f'email {EMAIL}', ollama(LOOPBACK), mode='refuse')