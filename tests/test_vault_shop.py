"""The vault host and the cart: the seams the notebooks do not cover.

The notebooks show these working. What is worth a plain test is what happens when they do
*not* work -- a vault that will not open, a store that raises, a host with neither -- because
that is the behaviour the harness promises and the one nobody exercises by hand.
"""
import time

import pytest

from ramabana.tools import ERR, NullHost, WRITE_TOOLS, failed, tools_for, watch_tools
from ramabana.shop import CartError, Cart, FakeCart, cart_tools


def names(tools): return {t.__name__ for t in tools}


# -- the watch contract ------------------------------------------------------

def test_a_host_without_watches_is_not_offered_the_watch_tools():
    assert not (names(tools_for(NullHost())) & names(watch_tools(NullHost())))


def test_watch_tools_report_a_missing_capability_instead_of_raising():
    "Every one of them is reachable on a host that supports none of it, and none of them raise."
    ts = {t.__name__: t for t in watch_tools(NullHost())}
    # One spelling of failure, so the activity feed and `Agent.problems` need no prefix list.
    for call, why in [(lambda: ts['remember']('x'), 'could not remember'),
                      (lambda: ts['set_reminder']('x'), 'could not set reminder'),
                      (lambda: ts['watch_url']('https://x'), 'could not watch'),
                      (lambda: ts['list_watches'](), 'could not list'),
                      (lambda: ts['cancel_watch']('abc'), 'could not cancel'),
                      (lambda: ts['poll_watches'](), 'poll failed')]:
        out = call()
        assert failed(out) and out.startswith(ERR + why), out


def test_cancelling_a_watch_is_gated_like_a_write():
    assert 'cancel_watch' in WRITE_TOOLS
    assert 'set_reminder' not in WRITE_TOOLS   # setting one is cheap and reversible


# -- the vault host ----------------------------------------------------------

@pytest.fixture
def host(tmp_path):
    vh = pytest.importorskip('ramabana.vault')
    h = vh.VaultHost(roots=[tmp_path], vault=tmp_path / 'vault.db', index=False, web=False)
    return h.open_vault(wait=True)


def test_the_memory_group_appears_only_once_there_is_a_vault_behind_it(host):
    assert 'memory_search' not in names(tools_for(NullHost()))
    assert {'memory_search', 'memory_tree', 'poll_watches'} <= names(tools_for(host))


def test_a_reminder_comes_back_as_something_memory_can_find(host):
    w = host.watch('buy milk', action='remind', every='1d', start=time.time() - 1)
    assert host.poll()['ran'] == 1
    found = host.memory_search('what should I buy', limit=3)
    assert any('milk' in s['text'] for s in found['results'])
    assert host.watches()[0]['next_run'] > w['next_run']    # it rescheduled itself


def test_a_failing_watch_is_recorded_rather_than_raised_and_the_rest_still_run(host):
    def down(target, **kw): raise ConnectionError('name not resolved')
    host.vault.url = down
    host.watch('https://example.invalid', action='url', every='1d', start=time.time() - 1)
    host.watch('still fine', action='remind', every='1d', start=time.time() - 1)
    out = host.poll()
    assert {r['action']: r['status'] for r in out['results']} == {'url': 'error', 'remind': 'ok'}


def test_search_degrades_to_the_local_one_when_the_vault_cannot_answer(host, tmp_path):
    "A broken vault must cost the extra leg, not the tool."
    (tmp_path / 'a.py').write_text('def widget(): pass\n')
    def boom(*a, **kw): raise RuntimeError('vault is gone')
    host.vault.federate = boom
    assert [h.path for h in host.search('widget')]           # ripgrep still answered
    assert 'federate_error' in host.search_note


def test_federate_off_leaves_localhost_search_exactly_as_it_was(host):
    host.federate = False
    assert 'federated' not in host.search_note


# -- the cart ----------------------------------------------------------------

def test_cart_is_an_interface_and_says_so():
    for call in (lambda c: c.open('u'), lambda c: c.find('q'), lambda c: c.add('x'),
                 lambda c: c.lines(), lambda c: c.total()):
        with pytest.raises(NotImplementedError): call(Cart())


def test_adding_by_a_title_the_store_does_not_stock_names_what_it_does():
    cart = FakeCart()
    with pytest.raises(CartError) as e: cart.add('caviar')
    assert 'Full Cream Milk 2L' in str(e.value)     # the real options, not a guess


def test_an_index_only_means_anything_against_the_search_that_produced_it():
    cart = FakeCart()
    cart.find('milk')
    assert cart.add(0)['item']['title'] == 'Full Cream Milk 2L'
    with pytest.raises(CartError): cart.add(3)      # the page has one row, not the whole store


def test_a_title_still_resolves_after_a_narrower_search():
    "The real cart re-reads the page for every add, so a stale search must not strand a title."
    cart = FakeCart()
    cart.find('milk')
    assert cart.add('Sourdough Loaf 680g')['ok']


def test_moving_store_changes_what_is_stocked_but_not_the_trolley():
    cart = FakeCart()
    cart.add('milk')
    cart.open('https://members.ceresfairfood.org.au')
    assert not cart.find('milk')
    assert cart.add('Seasonal Fruit Box - Medium')['ok']
    assert cart.total() == {'count': 2, 'subtotal': '$42.60'}


def test_the_tools_report_a_bad_add_rather_than_ending_the_turn():
    ts = {t.__name__: t for t in cart_tools(FakeCart())}
    out = ts['cart_add']('caviar')
    assert failed(out) and out.startswith(ERR + "could not add 'caviar'"), out
    assert 'no products matching' in ts['cart_find']('caviar')


def test_spending_money_is_gated_like_a_write():
    assert {'cart_add', 'cart_remove'} <= WRITE_TOOLS
    assert 'cart_find' not in WRITE_TOOLS


def test_the_vault_answers_on_this_sessions_model_rather_than_loading_its_own(tmp_path):
    """vishalakshi builds a `rishi.Chat` per `ask` from `$VISHALAKSHI_MODEL`. Unlent, that is a
    second engine beside the one already running, answering on a different model."""
    from ramabana.vault import VaultHost
    from ramabana.agent import Agent
    from ramabana.tools import LocalHost

    host = VaultHost(roots=(str(tmp_path),), vault=str(tmp_path/'v.db'), index=False, web=False)
    assert host.mk_chat is None
    agent = Agent(host, model='gpt-mini', extensions=False, subagents=False)
    assert agent.lend_model() is True
    assert callable(host.mk_chat)
    assert agent.lend_model() is False          # never replaces a factory somebody chose

    plain = LocalHost(roots=(str(tmp_path),), index=False, web=False)
    assert Agent(plain, model='gpt-mini', extensions=False, subagents=False).lend_model() is False
    assert not hasattr(plain, 'mk_chat')

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


def _fake_chat(runtime, reply, sent):
    def mk(model=None, **kw):
        class C:
            use, hist = None, []
            def __init__(s): s.runtime = runtime
            def __call__(s, prompt, **k):
                sent.append((runtime, model, prompt, kw.get('sp', '')))
                return {'role': 'assistant', 'content': reply}
        return C()
    return mk


def _private_host(tmp_path):
    from ramabana.vault import VaultHost
    host = VaultHost(roots=(str(tmp_path),), vault=str(tmp_path/'v.db'), index=False, web=False)
    host.vault.note('Invoice 4471 for Ada Lovelace, ada@example.com, phone 020 7946 0958. '
                    'Card 4111 1111 1111 1111. Amount 240.00 GBP, due 2026-09-01.', title='invoice 4471')
    host.vault.note('The deploy pipeline runs on GitHub Actions and takes about 20 minutes.',
                    title='pipeline')
    return host


def test_private_sections_never_reach_a_hosted_model(tmp_path):
    "A hosted chat lent for a private question is refused before a character is sent."
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('remote', 'THIS MUST NEVER BE SENT', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.refused is True
    assert 'not a local runtime' in r.answer
    assert sent == []


def test_a_local_model_answers_it_under_a_briefing_that_forbids_the_details(tmp_path):
    from vishalakshi.ask import PII_SP
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('litert', 'One invoice, 240.00 GBP, due in September. Holding back '
                                        'the name, email and card. Tell me what you need.', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.get('refused', False) is False
    assert sent[0][0] == 'litert' and sent[0][3] == PII_SP
    assert r.pii.has_pii and set(r.pii.identifying) == {'card', 'email', 'phone'}


def test_the_instruction_comes_back_for_a_second_turn(tmp_path):
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('litert', 'Total 240.00 GBP, due 2026-09-01.', sent)
    r = host.ask('what is on invoice 4471?', instruction='Give me the total and the due date only.')
    assert 'Instruction from the questioner' in sent[0][2]
    assert r.answer == 'Total 240.00 GBP, due 2026-09-01.'


def test_a_local_model_that_leaks_anyway_is_masked_on_the_way_out(tmp_path):
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('litert', 'It is for ada@example.com, card 4111 1111 1111 1111.', sent)
    r = host.ask('what is on invoice 4471?')
    assert r.answer == 'It is for [EMAIL], card [CARD].'
    assert set(r.leaked) == {'email', 'card'}


def test_the_model_cannot_switch_the_gate_off_through_the_tool(tmp_path):
    "`pii='off'` is a caller's setting, not an argument reachable from the far end of a tool call."
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('remote', 'LEAKED', sent)
    assert host.ask('what is on invoice 4471?', pii='off').refused is True
    assert sent == []


def test_private_filler_is_dropped_rather_than_making_the_question_private(tmp_path):
    """`doc_context` puts sections from elsewhere behind the document asked about. One of those
    being private should cost that section, not send the whole answer to a smaller model."""
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('remote', 'About 20 minutes [1]', sent)
    r = host.ask('how long does the pipeline take?', ref='pipeline')
    assert r.pii.has_pii is False
    assert sent[0][0] == 'remote'
    assert 'ada@example.com' not in sent[0][2]


def test_ask_memory_appears_only_for_a_host_that_can_ask(tmp_path):
    from ramabana.tools import tools_for, LocalHost
    from ramabana.testing import FullHost
    names = lambda h: {t.__name__ for t in tools_for(h)}
    assert 'ask_memory' in names(_private_host(tmp_path))
    assert 'ask_memory' not in names(FullHost())          # has the memory group, has no model to ask
    assert 'ask_memory' not in names(LocalHost(roots=(str(tmp_path),), index=False, web=False))


def test_ask_memory_tells_the_model_what_it_can_ask_for_next(tmp_path):
    from ramabana.tools import tools_for
    host, sent = _private_host(tmp_path), []
    host.mk_chat = _fake_chat('litert', 'One invoice, 240.00 GBP. Holding back the details.', sent)
    ask_memory = {t.__name__: t for t in tools_for(host)}['ask_memory']
    out = ask_memory('what is on invoice 4471?')
    assert 'One invoice, 240.00 GBP' in out
    assert 'answered on a local model' in out and 'instruction=' in out


def test_a_lent_factory_honours_the_model_it_is_asked_for(tmp_path):
    """The vault names its local model and then checks what came back really runs here, so a
    factory that ignored the name would be handing a statement to a hosted API."""
    from ramabana.agent import Agent
    host = _private_host(tmp_path)
    agent = Agent(host, model='gpt-mini', extensions=False, subagents=False)
    assert agent.lend_model() is True
    spec = agent._spec_for('gemma-e4b')
    assert spec is not None and spec.runtime == 'litert' and spec.local is True
    assert agent._spec_for('mlx/not-installed-here') is None
