"A llama model's window comes from its GGUF metadata, read through rishi's public `get_model`."
import sys, types
import rishi.llama
from ramabana.core import local_window


def test_llama_window_reads_the_model_rishi_fetches(monkeypatch):
    seen = []
    class Llama:
        def __init__(self, path, **kw): seen.append(path); self.metadata = {'general.architecture': 'qwen3', 'qwen3.context_length': '40960'}
    monkeypatch.setitem(sys.modules, 'llama_cpp', types.SimpleNamespace(Llama=Llama))
    monkeypatch.setattr(rishi.llama, 'get_model', lambda model_id, *a, **kw: f'/models/{model_id}.gguf')
    local_window.cache_clear()
    assert local_window('llama', 'qwen-test') == 40960 and seen == ['/models/qwen-test.gguf']
