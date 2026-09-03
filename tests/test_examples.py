"""The example notebook, run as far as it goes without a model.

`examples/pii_wall.ipynb` is a showcase, so its first three cells have to keep working against
whatever vishalakshi and shalya do next. Nothing here loads a model or reaches the network.
"""
import os
from pathlib import Path

import pytest
from fastcore.nbio import read_nb

EXAMPLES = Path(__file__).parent.parent/'examples'
NB = EXAMPLES/'pii_wall.ipynb'


def _run(n, monkeypatch):
    "The notebook's first `n` code cells, in one namespace, offline and from `examples/`."
    monkeypatch.setenv('VISHALAKSHI_OFFLINE', '1')
    monkeypatch.chdir(EXAMPLES)
    ns = {}
    for c in [c.source for c in read_nb(NB).cells if c.cell_type == 'code'][:n]:
        exec(compile(c, str(NB), 'exec'), ns)
    return ns


def test_the_example_corpus_is_the_one_the_notebook_marks_up():
    names = sorted(p.name for p in (EXAMPLES/'inbox').rglob('*.md'))
    assert names == ['callback-2024-03-14.md', 'refund-8842.md', 'refund-8845.md',
                     'refund-8851.md', 'refund-runbook.md', 'scheme-terms.md']


def test_a_persons_marks_decide_what_arithmetic_could_not(monkeypatch):
    ns = _run(3, monkeypatch)
    v, folder = ns['v'], ns['folder']
    private = {Path(d['source']).name for d in v.docs if v.pii(d['source'], ner=True).has_pii}
    assert private == {'refund-8842.md', 'refund-8845.md', 'refund-8851.md',
                       'callback-2024-03-14.md'}
    assert v.pii(str(folder/'letters/refund-8851.md')).detected is False   # marked, not detected
    assert v.pii(str(folder/'ops/refund-runbook.md')).detected is True     # detected, then cleared


def test_the_seal_raises_before_a_prompt_with_personal_data_reaches_a_hosted_model(monkeypatch):
    ns = _run(2, monkeypatch)
    class Deaf:
        def ask(self, prompt, **kw): raise AssertionError('the hosted agent was reached')
    sealed = ns['sealed'](Deaf())
    with pytest.raises(ns['Leak']): sealed.ask('refund ada@example.com her 240.00 EUR')
    assert ns['WIRE'] == []
