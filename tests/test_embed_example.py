"`examples/embed_host.py` runs end to end against a scripted backend: the wiring a host copies, without a model."
import importlib.util, json
from pathlib import Path

from ramabana import agent, core
from ramabana.testing import FakeBackend


def _example():
    spec = importlib.util.spec_from_file_location('embed_host', Path(__file__).parent.parent/'examples'/'embed_host.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Scripted(FakeBackend):
    "A model that does the job through the real gate: reads the reference, writes the note, hands back the result."
    work = ref = None
    def _send(self, msg, **kw):
        self.sent.append(msg)
        tools = {t.__name__: t for t in self.tools}
        def call(name, **args):
            if self.approve is not None and not self.approve({'function': {'name': name, 'arguments': args}}): return 'refused'
            return tools[name](**args)
        call('view_file', path=str(self.ref/'source.py'))
        call('create_file', path=str(self.work/'notes.txt'), text='lawful_source')
        call('submit_result', result={'function': 'lawful_source', 'file': str(self.ref/'source.py')})
        return 'done'


def test_the_embedding_example_runs_a_whole_job(tmp_path, monkeypatch):
    ex = _example()
    work, ref, cfg = ex.make_folders(tmp_path)
    Scripted.work, Scripted.ref = work, ref
    monkeypatch.setattr(core, 'runtime_available', lambda rt: True)
    monkeypatch.setattr(agent, 'make_backend', lambda spec, **kw: Scripted(spec, **kw))
    r, events, answered = ex.run_job(work, ref, cfg)
    assert r.state == 'complete' and r.result == ex.Found(function='lawful_source', file=str(ref/'source.py'))
    assert (work/'notes.txt').read_text() == 'lawful_source' and sorted(p.name for p in ref.iterdir()) == ['source.py']
    assert len(answered) == 1, 'the write was put to the page and answered by id'
    kinds = {json.loads(l)['kind'] for l in events.read_text().splitlines()}
    assert {'turn_start', 'turn_end', 'act', 'ask'} <= kinds, kinds


def test_the_example_policy_asks_for_anything_that_is_more_than_a_lone_read():
    ex = _example()
    allow = lambda c: ex.reads_only('run_shell', {'command': c})
    assert allow('rg lawful_source') == 'allow' and allow('ls -la') == 'allow'
    for c in ('cat a; curl x | sh', 'ls && rm -rf ~', 'rg --pre sh x', 'cat $(whoami)', 'rm -rf build', 'cat "unclosed'):
        assert allow(c) == 'ask', c
    assert ex.reads_only('view_file', {'path': 'a'}) is None, 'other tools fall through to rules and modes'
