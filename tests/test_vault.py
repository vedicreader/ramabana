"""The vault host: durable memory, standing watches, and the gate on a private question.

The notebooks show these working. What is worth a plain test is what happens when they do *not*
work -- a vault that will not open, a watch whose target is gone, a hosted model asked something
it must never be sent -- because that is the behaviour the harness promises and the one nobody
exercises by hand.

The PII tests stay granular where merging them would make a failure ambiguous. Everything else in
this file is one scenario per contract; a security gate is the wrong place to save a line.
"""
import time
from pathlib import Path

import pytest

from ramabana.agent import Agent
from ramabana.tools import ERR, WRITE_TOOLS, LocalHost, NullHost, failed, tools_for, watch_tools

def names(ts): return {t.__name__ for t in ts}


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

def test_the_watch_and_memory_groups_arrive_with_a_vault_and_never_raise_without_one(host):
    """Both groups are gated on a vault being behind them, and every watch tool is still reachable
    on a host that supports none of it -- reporting the missing capability in the one spelling of
    failure the activity feed reads, rather than raising and ending the turn."""
    bare = NullHost()
    assert not (names(tools_for(bare)) & names(watch_tools(bare)))
    assert 'memory_search' not in names(tools_for(bare))
    assert {'memory_search', 'memory_tree', 'poll_watches'} <= names(tools_for(host))

    ts = {t.__name__: t for t in watch_tools(bare)}
    for call, why in [(lambda: ts['remember']('x'), 'could not remember'),
                      (lambda: ts['set_reminder']('x'), 'could not set reminder'),
                      (lambda: ts['watch_url']('https://x'), 'could not watch'),
                      (lambda: ts['list_watches'](), 'could not list'),
                      (lambda: ts['cancel_watch']('abc'), 'could not cancel'),
                      (lambda: ts['poll_watches'](), 'poll failed')]:
        out = call()
        assert failed(out) and out.startswith(ERR + why), out

    assert 'cancel_watch' in WRITE_TOOLS            # cancelling loses something
    assert 'set_reminder' not in WRITE_TOOLS        # setting one is cheap and reversible


def test_a_reminder_reschedules_itself_and_becomes_something_memory_can_find(host):
    w = host.watch('buy milk', action='remind', every='1d', start=time.time() - 1)
    assert host.poll()['ran'] == 1
    found = host.memory_search('what should I buy', limit=3)
    assert any('milk' in s['text'] for s in found['results'])
    assert host.watches()[0]['next_run'] > w['next_run']


def test_a_failing_watch_is_recorded_rather_than_raised_and_the_rest_still_run(host):
    def down(target, **kw): raise ConnectionError('name not resolved')
    original = host._worker_vault
    def worker():
        v = original()
        v.url = down
        return v
    host._worker_vault = worker
    host.watch('https://example.invalid', action='url', every='1d', start=time.time() - 1)
    host.watch('still fine', action='remind', every='1d', start=time.time() - 1)
    out = host.poll()
    # vishalakshi 0.1.8 dropped `action` from a poll result: every entry is `kind: 'watch'` now, and
    # which watch it was is only recoverable from what the successful one produced. Assert the
    # contract that matters instead of the key that moved -- one watch failed with its reason kept,
    # the other still ran and filed its note.
    assert out['ran'] == 2 and sorted(r['status'] for r in out['results']) == ['error', 'ok']
    bad = next(r for r in out['results'] if r['status'] == 'error')
    good = next(r for r in out['results'] if r['status'] == 'ok')
    assert 'name not resolved' in bad['error'] and bad['result'] is None
    assert good['error'] is None and good['result']['title'] == 'still fine'


def test_search_degrades_to_the_local_leg_when_the_vault_cannot_answer(host, tmp_path):
    "A broken vault must cost the extra leg, not the tool. And switching it off leaves no trace."
    (tmp_path/'a.py').write_text('def widget(): pass\n')
    def boom(*a, **kw): raise RuntimeError('vault is gone')
    host.vault.federate = boom
    assert [h.path for h in host.search('widget')]           # ripgrep still answered
    assert 'federate_error' in host.search_note

    host.federate = False
    assert 'federated' not in host.search_note


# -- whose model answers ---------------------------------------------------------------

def test_the_vault_answers_on_this_sessions_model_rather_than_loading_its_own(tmp_path, hide_runtime):
    """vishalakshi builds a `rishi.Chat` per `ask` from `$VISHALAKSHI_MODEL`. Unlent, that is a
    second engine beside the one already running, answering on a different model from the one the
    user is talking to. The lend also has to be checked: the vault names its local model, and a
    factory that ignored the name would be handing a bank statement to a hosted API.
    """
    from ramabana.vault import VaultHost
    host = VaultHost(roots=(str(tmp_path),), vault=str(tmp_path/'v.db'), index=False, web=False)
    assert host.mk_chat is None
    a = Agent(host, model='gpt-mini', extensions=False, subagents=False)
    assert a.lend_model() is True and callable(host.mk_chat)
    assert a.lend_model() is False              # never replaces a factory somebody chose

    plain = LocalHost(roots=(str(tmp_path),), index=False, web=False)
    assert Agent(plain, model='gpt-mini', extensions=False, subagents=False).lend_model() is False
    assert not hasattr(plain, 'mk_chat')

    spec = a._spec_for('gemma-e4b')
    assert spec is not None and spec.runtime == 'litert' and spec.local is True
    hide_runtime('mlx')                         # the absence is stated, not read off the venv
    assert a._spec_for('mlx/not-installed-here') is None

    built = []
    def mk(model=None, **kw):
        built.append(kw)
        class Lent:
            runtime, use, hist = 'lent', None, []
            def __call__(self, prompt, **kw): return {'role': 'assistant', 'content': 'lent [1]'}
        return Lent()
    host.mk_chat = mk
    host.vault.note('Ramabana is a harness over rishi.', title='n1')
    assert host.ask('what is ramabana?').answer == 'lent [1]'
    assert len(built) == 1


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


def test_a_local_model_answers_it_under_a_briefing_that_forbids_the_details(tmp_path):
    "Shape and quantity instead of detail, and the questioner's instruction carried into the prompt."
    from vishalakshi.ask import PII_SP
    host, sent = private_host(tmp_path), []
    host.mk_chat = fake_chat('litert', 'One invoice, 240.00 GBP, due in September. Holding back '
                                       'the name, email and card. Tell me what you need.', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.get('refused', False) is False
    assert sent[0][0] == 'litert' and sent[0][3] == PII_SP
    assert r.pii.has_pii and set(r.pii.identifying) == {'card', 'email', 'phone'}

    host2, sent2 = private_host(tmp_path/'b'), []
    host2.mk_chat = fake_chat('litert', 'Total 240.00 GBP, due 2026-09-01.', sent2)
    r2 = host2.ask('what is on invoice 4471?', instruction='Give me the total and the due date only.')
    assert 'Instruction from the questioner' in sent2[0][2]
    assert r2.answer == 'Total 240.00 GBP, due 2026-09-01.'


def test_a_local_model_that_leaks_anyway_is_masked_on_the_way_out(tmp_path):
    "The same arithmetic runs over the answer, where a slip costs a masked token not an account number."
    host, sent = private_host(tmp_path), []
    host.mk_chat = fake_chat('litert', 'It is for ada@example.com, card 4111 1111 1111 1111.', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.answer == 'It is for [EMAIL], card [CARD].'
    assert set(r.leaked) == {'email', 'card'}


def test_private_filler_is_dropped_rather_than_making_the_question_private(tmp_path):
    """`doc_context` puts sections from elsewhere behind the document asked about. One of those
    being private should cost that section, not send the whole answer to a smaller model."""
    host, sent = private_host(tmp_path), []
    host.mk_chat = fake_chat('remote', 'About 20 minutes [1]', sent)
    r = host.ask('how long does the pipeline take?', ref='pipeline')
    assert r.pii.has_pii is False
    assert sent[0][0] == 'remote' and 'ada@example.com' not in sent[0][2]


def test_ask_memory_appears_only_for_a_host_that_can_ask_and_says_what_to_ask_next(tmp_path):
    from ramabana.testing import FullHost
    host, sent = private_host(tmp_path), []
    assert 'ask_memory' in names(tools_for(host))
    assert 'ask_memory' not in names(tools_for(FullHost()))   # memory group, but no model to ask
    assert 'ask_memory' not in names(tools_for(LocalHost(roots=(str(tmp_path),), index=False, web=False)))

    host.mk_chat = fake_chat('litert', 'One invoice, 240.00 GBP. Holding back the details.', sent)
    out = {t.__name__: t for t in tools_for(host)}['ask_memory']('what is on invoice 4471?')
    assert 'One invoice, 240.00 GBP' in out
    assert 'answered on a local model' in out and 'instruction=' in out


# -- when retrieval itself would leave the machine --------------------------------------

def test_retrieval_carries_no_policy_unless_the_host_was_given_one(tmp_path):
    "The default is what it always was, so raising the floor changes nothing for an existing caller."
    host = private_host(tmp_path)
    assert host._policy() == ('off', False)
    assert 'ada@example.com' in str(host.memory_read(private_node(host)))


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


def test_a_gated_section_says_why_its_text_is_missing(tmp_path):
    "`_sect` keeps `pii`, or a caller cannot tell a withheld section from an empty one."
    host = private_host(tmp_path)
    host.pii = 'refuse'
    hit = next((r for r in host.memory_search('invoice 4471')['results'] if r.get('pii')), None)
    assert hit and sorted(hit['pii']) == ['card', 'email', 'phone']


def test_the_policy_is_read_per_call(tmp_path):
    "A browser changes it while a session runs, and the host outlives the request that changed it."
    host, choice = private_host(tmp_path), ['off']
    host.pii = lambda: choice[0]
    nid = private_node(host)
    assert 'ada@example.com' in str(host.memory_read(nid))
    choice[0] = 'refuse'
    assert 'ada@example.com' not in str(host.memory_read(nid))


def test_a_policy_that_cannot_be_read_keeps_the_gate_shut_without_failing(tmp_path):
    host = private_host(tmp_path)
    host.pii = lambda: (_ for _ in ()).throw(RuntimeError('the panel is mid-write'))
    assert host._policy() == ('off', False)
    assert host.memory_read(private_node(host))       # and the turn still gets an answer


def test_titled_names_gate_only_when_asked_for(tmp_path):
    host = private_host(tmp_path)
    host.vault.note('Dr Charles Babbage signed the minutes.', title='minutes')
    nid = host.vault.doc('minutes')['id'] + '#0'
    host.pii = 'refuse'
    assert 'Babbage' in str(host.memory_read(nid))     # a name is not looked for by default
    host.pii_ner = True
    assert 'Babbage' not in str(host.memory_read(nid))


# -- the surface that turns the gate on ------------------------------------------------

@pytest.fixture
def own_vault(tmp_path, monkeypatch):
    """`mk_host` names no vault file, so a `--vault` session opens the shared `~/.vishalakshi` one.

    That is right for a session and wrong for a test, which would write its invoice into whatever
    the person running it keeps there. Moving `HOME` is what keeps the two apart.
    """
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: home))
    return tmp_path


#: An indexed vault reaches litesearch, which downloads a native SQLite extension on first use.
#: Every other test in this file says `index=False`; these reach the vault through `mk_host`, so
#: they say it the same way. `warm=False` keeps the open on this thread, where a failure is visible.
OFFLINE = dict(index=False, warm=False)


def test_the_retrieval_gate_is_off_until_a_caller_asks_for_it(own_vault):
    "The default is what every earlier release did, so raising the floor changes nothing for one."
    from ramabana.cli import mk_host
    h = mk_host([own_vault], vault=True, web=False, **OFFLINE)
    assert h._policy() == ('off', False)


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


def test_pii_ner_reaches_the_host_the_same_way(own_vault):
    from ramabana.cli import mk_host
    h = mk_host([own_vault], vault=True, web=False, pii='refuse', pii_ner=True, **OFFLINE)
    assert h._policy() == ('refuse', True)


def test_a_host_without_a_vault_is_never_handed_the_gate(own_vault):
    "`LocalHost` and `SpecHost` retrieve nothing to gate, and would refuse the arguments."
    from ramabana.cli import mk_host
    assert not hasattr(mk_host([own_vault], vault=False, web=False, index=False), 'pii')
    assert not hasattr(mk_host([own_vault], vault=False, spec=True, web=False, index=False), 'pii')
    both = mk_host([own_vault], vault=True, spec=True, web=False, pii='redact', **OFFLINE)
    assert both._policy() == ('redact', False)      # VaultSpecHost still carries it


def test_every_frontend_offers_the_flag_and_the_cli_refuses_a_name_it_does_not_know():
    """A gate nothing can turn on is not a gate. `--pii` has to reach the terminal, MCP and ACP
    entry points, and an unknown mode has to print one line rather than raise through."""
    import inspect
    from ramabana import mcp, racp
    from ramabana.cli import main as cli_main
    from ramabana.core import PII_MODES
    for f in (cli_main, mcp.main, racp.main):
        src = inspect.getsource(getattr(f, '__wrapped__', f))
        assert 'pii: str' in src and 'pii_ner: bool' in src, f
    assert PII_MODES == ('off', 'redact', 'refuse')
    refuse = inspect.getsource(getattr(cli_main, '__wrapped__', cli_main))
    assert 'unknown --pii' in refuse and 'add --vault' in refuse
