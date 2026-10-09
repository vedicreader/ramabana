"""The memo every probe about this machine shares, and the seam an application fills.

Two faults behind this file. `Completer._prompt` reached `self.a.ws.agent_memory_context(...)`;
nothing in Ramabana ever sets `Agent.ws`, so the call raised `AttributeError` into a bare `except`
and a person's pinned notes never reached a completion prompt anywhere. And three copies of the
same idea existed at once: `_oai_cache` and `_copilot_cat` as bare module tuples here, and a fuller
`probed` in Leela with disk persistence and a background refresh.
"""
import json
import time

import pytest

from ramabana.agent import Completer
from ramabana.core import forget_probes, load_models, probed, save_model, saved_models, unregister_model
from ramabana.tools import NullHost


@pytest.fixture
def probes(tmp_path):
    forget_probes()
    yield tmp_path
    forget_probes()


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


def test_the_completer_asks_the_agent_rather_than_an_attribute_only_leela_set():
    class Embedder:
        host = NullHost()
        def memory_context(self, surface, max_chars=6000): return f'note for {surface}'
    prompt = Completer(Embedder())._prompt('x = 1', 5, 'python')
    assert '<user_memory>\nnote for completion\n</user_memory>' in prompt


def test_a_row_naming_a_runtime_that_is_gone_does_not_cost_the_others(tmp_path):
    p = tmp_path/'models.json'
    save_model({'name': 'good', 'model_id': 'openai/good', 'runtime': 'remote', 'ctx': 128_000}, p)
    rows = [{'name': 'gone', 'model_id': 'x/y', 'runtime': 'no-such-runtime', 'ctx': 128_000}, *saved_models(p)]
    p.write_text(json.dumps(rows))
    try: assert [r['name'] for r in load_models(p)] == ['good']
    finally: unregister_model('good')
