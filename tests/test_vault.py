"""The vault host: durable memory, standing watches, and the gate on a private question.

The notebooks show these working. What is worth a plain test is what happens when they do *not*
work -- a vault that will not open, a watch whose target is gone, a hosted model asked something
it must never be sent -- because that is the behaviour the harness promises and the one nobody
exercises by hand.

The PII tests stay granular where merging them would make a failure ambiguous. Everything else in
this file is one scenario per contract; a security gate is the wrong place to save a line.
"""
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def host(tmp_path):
    vh = pytest.importorskip('ramabana.vault')
    h = vh.VaultHost(roots=[tmp_path], vault=tmp_path/'vault.db', index=False, web=False)
    return h.open_vault(wait=True)


def fake_chat(runtime, reply, sent):
    "A `mk_chat` factory standing in for a lent engine, recording what it was asked to send."
    def mk(model=None, **kw):
        class C:
            use, hist = None, []
            def __init__(s): s.runtime = runtime
            def __call__(s, prompt, **k):
                sent.append((runtime, model, prompt, kw.get('sp', '')))
                return {'role': 'assistant', 'content': reply}
        return C()
    return mk


def private_host(tmp_path):
    "A vault holding one private document and one that is nobody's business but the project's."
    from ramabana.vault import VaultHost
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    h = VaultHost(roots=(str(tmp_path),), vault=str(tmp_path/'v.db'), index=False, web=False)
    h.vault.note('Invoice 4471 for Ada Lovelace, ada@example.com, phone 020 7946 0958. '
                 'Card 4111 1111 1111 1111. Amount 240.00 GBP, due 2026-09-01.', title='invoice 4471')
    h.vault.note('The deploy pipeline runs on GitHub Actions and takes about 20 minutes.',
                 title='pipeline')
    return h


def private_node(host, title='invoice 4471'):
    "The one section of the private document, by node id."
    return host.vault.doc(title)['id'] + '#0'


# -- watches ---------------------------------------------------------------------------


def test_a_reminder_reschedules_itself_and_becomes_something_memory_can_find(host):
    w = host.watch('buy milk', action='remind', every='1d', start=time.time() - 1)
    assert host.poll()['ran'] == 1
    found = host.memory_search('what should I buy', limit=3)
    assert any('milk' in s['text'] for s in found['results'])
    assert host.watches()[0]['next_run'] > w['next_run']


# -- when the answer would leave the machine -------------------------------------------

def test_private_sections_never_reach_a_hosted_model(tmp_path):
    """Refused before a character is sent, and `pii='off'` is a caller's setting rather than an
    argument reachable from the far end of a tool call."""
    host, sent = private_host(tmp_path), []
    host.mk_chat = fake_chat('remote', 'THIS MUST NEVER BE SENT', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.refused is True and 'not a local runtime' in r.answer
    assert sent == []
    assert host.ask('what is on invoice 4471?', pii='off').refused is True
    assert sent == []


def test_a_local_model_that_leaks_anyway_is_masked_on_the_way_out(tmp_path):
    "The same arithmetic runs over the answer, where a slip costs a masked token not an account number."
    host, sent = private_host(tmp_path), []
    host.mk_chat = fake_chat('litert', 'It is for ada@example.com, card 4111 1111 1111 1111.', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.answer == 'It is for [EMAIL], card [CARD].'
    assert set(r.leaked) == {'email', 'card'}


# -- when retrieval itself would leave the machine --------------------------------------


@pytest.mark.parametrize('act', ['redact', 'refuse'])
def test_a_policy_reaches_every_tool_that_returns_section_text(tmp_path, act):
    """`ask` was the only one that had a gate, so these four handed raw sections to the turn model.

    Vishalakshi applies the policy; the host only carries it.
    """
    host = private_host(tmp_path)
    host.pii = act
    nid = private_node(host)
    for got in (host.memory_read(nid), host.memory_search('invoice 4471'),
                host.search('invoice 4471'), host.memory_tree()):
        assert 'ada@example.com' not in str(got)
        assert '020 7946 0958' not in str(got)


# -- the surface that turns the gate on ------------------------------------------------

@pytest.fixture
def own_vault(tmp_path, monkeypatch):
    "A private `HOME` keeps the test out of `~/.vishalakshi`; `VIRTUAL_ENV` points litesearch at this venv's usearch."
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('VIRTUAL_ENV', sys.prefix)
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: home))
    return tmp_path


#: an indexed vault downloads a SQLite extension on first use, and `warm=False` keeps the open here
OFFLINE = dict(index=False, warm=False)


@pytest.mark.parametrize('mode', ['redact', 'refuse'])
def test_mk_host_carries_pii_into_every_vault_read(own_vault, mode):
    """`VaultHost` took `pii` and nothing built one with it, so no ramabana frontend could reach
    the gate at all. Leela set it from its own panel; a `ramabana --vault` session could not."""
    from ramabana.cli import mk_host
    h = mk_host([own_vault], vault=True, web=False, pii=mode, **OFFLINE)
    h.open_vault(wait=True)
    h.vault.note('Ada Lovelace, ada@example.com, phone 020 7946 0958.', title='contact')
    assert h._policy() == (mode, False)
    got = str(h.memory_read(h.vault.doc('contact')['id'] + '#0'))
    assert 'ada@example.com' not in got and '020 7946 0958' not in got




def test_the_entity_graph_waits_for_a_model_chosen_for_it(tmp_path, monkeypatch):
    """With no graph model, vishalakshi built its graph on its local default, so a session using only
    cloud models loaded Gemma 4 on LiteRT mid-turn. Topic nodes need no model and still update."""
    import vishalakshi
    monkeypatch.delenv('VISHALAKSHI_MODEL', raising=False)
    built = []
    monkeypatch.setattr(vishalakshi.Vault, 'build_graph', lambda self, chat=None, **kw: built.append(chat) or dict(entities=0, mentions=0, edges=0, new=0))
    h = private_host(tmp_path)
    h.connect(wait=True)
    assert built == [], 'no graph model was chosen, so no local model is loaded'
    h.graph_chat = chat = object()
    h.connect(wait=True)
    assert built == [chat]
