"""The example notebook, run as far as it goes without a model.

`examples/pii_wall.ipynb` is a showcase, so its wall has to keep holding against whatever
vishalakshi and shalya do next. Nothing here loads a model or reaches the network.
"""
from pathlib import Path

import pytest
from fastcore.nbio import read_nb

EXAMPLES = Path(__file__).parent.parent/'examples'
NB = EXAMPLES/'pii_wall.ipynb'
LEAKY = {'run_shell', 'run_python', 'read_url', 'web_search', 'watch_url', 'git_remote',
         'delegate_search', 'delegate_parallel', 'delegate_async'}


def _run(defines, monkeypatch):
    "Execute code cells until every name in `defines` is bound, offline and from `examples/`."
    monkeypatch.setenv('VISHALAKSHI_OFFLINE', '1')
    monkeypatch.chdir(EXAMPLES)
    ns = {}
    for c in [c.source for c in read_nb(NB).cells if c.cell_type == 'code']:
        if set(defines) <= set(ns): break
        exec(compile(c, str(NB), 'exec'), ns)
    assert set(defines) <= set(ns), f'the notebook no longer defines {set(defines) - set(ns)}'
    return ns


class Deaf:
    "A stand-in for the hosted agent. Reaching it is the failure the seal exists to prevent."
    def __init__(self, reply='a plan'): self.reply = reply
    def ask(self, prompt, **kw): return self.reply
    def stream(self, prompt, **kw): return iter([self.reply])


def test_the_example_corpus_is_the_one_the_notebook_marks_up():
    names = sorted(p.name for p in (EXAMPLES/'inbox').rglob('*.md'))
    assert names == ['callback-2024-03-14.md', 'refund-8842.md', 'refund-8845.md',
                     'refund-8851.md', 'refund-runbook.md', 'scheme-terms.md']


def test_the_notebook_is_committed_with_no_outputs():
    "`nbdev-clean` only walks nbs/, so the one notebook that could print records is unguarded."
    for c in read_nb(NB).cells:
        assert not c.get('outputs'), f'cell {c.idx_} carries output'
        assert not c.get('execution_count')


def test_a_persons_marks_decide_what_arithmetic_could_not(monkeypatch):
    ns = _run(['v', 'folder'], monkeypatch)
    v, folder = ns['v'], ns['folder']
    private = {Path(d['source']).name for d in v.docs if v.pii(d['source'], ner=True).has_pii}
    assert private == {'refund-8842.md', 'refund-8845.md', 'refund-8851.md',
                       'callback-2024-03-14.md'}
    assert v.pii(str(folder/'letters/refund-8851.md')).detected is False   # marked, not detected
    assert v.pii(str(folder/'ops/refund-runbook.md')).detected is True     # detected, then cleared


def test_private_terms_covers_the_names_and_numbers_the_detector_cannot_see(monkeypatch):
    "`pii_report` is honorific-anchored, so a bare surname and a case number reach it clean."
    ns = _run(['v', 'NAMES', 'private_terms', 'pii_report'], monkeypatch)
    terms = ns['private_terms'](ns['v'], ns['NAMES'])
    assert {'okafor', 'nowak', 'jane', '8842', '8851'} <= terms
    assert not ns['pii_report']('Amara Okafor, case 8851', ner=True).has_pii
    assert not {'refund', 'card', 'three', 'every', 'returned', 'runbook'} & terms


def test_the_seal_refuses_a_prompt_that_names_a_record_and_passes_a_clean_one(monkeypatch):
    ns = _run(['v', 'NAMES', 'sealed', 'Wall'], monkeypatch)
    up = ns['sealed'](Deaf(), ns['v'], ns['NAMES'])
    for bad in ('Amara Okafor is still out 240.00 EUR', 'cases 8842 and 8851 bounced',
                'refund ada@example.com', 'card 4111 1111 1111 1111'):
        with pytest.raises(ns['Wall']): up.ask(bad)
    assert up.wire == []
    assert up.ask('three refunds went out on card rails and the bank returned them') == 'a plan'
    assert len(up.wire) == 1


def test_the_seal_will_not_hand_back_a_failed_turn_as_a_plan(monkeypatch):
    ns = _run(['v', 'NAMES', 'sealed', 'Wall'], monkeypatch)
    up = ns['sealed'](Deaf('the assistant failed (no credential)'), ns['v'], ns['NAMES'])
    with pytest.raises(ns['Wall']): up.ask('what is the scheme rule?')


def test_the_half_holding_the_records_cannot_shell_out_delegate_or_fetch(monkeypatch):
    ns = _run(['v', 'folder', 'inside'], monkeypatch)
    down = ns['inside'](ns['v'], ns['folder'])
    names = {t.__name__ for t in down.tools}
    assert not names & LEAKY
    assert {'create_file', 'edit_file', 'view_file', 'ask_memory'} <= names
    assert down.subagents is False


def test_the_hosted_half_may_only_propose(monkeypatch):
    ns = _run(['v', 'NAMES', 'outside'], monkeypatch)
    up = ns['outside'](ns['v'], ns['NAMES'])
    names = {t.__name__ for t in up.tools}
    assert not names & {'create_file', 'edit_file', 'replace_text', 'run_shell', 'run_python'}
    assert {'read_url', 'web_search'} <= names
    assert up.host.roots and not [x for r in up.host.roots for x in Path(r).iterdir()]
