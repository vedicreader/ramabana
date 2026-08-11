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
