"""The trolley: `fossick.shop` behind a small interface, and what it does when an add cannot land.

Its own block because it is its own subject. What the notebooks do not show is the failure shape,
which is the whole reason the interface exists: a model that asked for caviar should learn what
the store actually stocks rather than have its turn end.
"""
import pytest

from ramabana.shop import Cart, CartError, FakeCart, cart_tools
from ramabana.tools import ERR, WRITE_TOOLS, failed


def test_cart_is_an_interface_and_says_so():
    for call in (lambda c: c.open('u'), lambda c: c.find('q'), lambda c: c.add('x'),
                 lambda c: c.lines(), lambda c: c.total()):
        with pytest.raises(NotImplementedError): call(Cart())


def test_an_add_resolves_by_title_or_by_the_search_that_produced_the_index():
    """An index means nothing except against the page it came from, and a title has to keep
    resolving after a narrower search because the real cart re-reads the page for every add.
    Changing store changes what is stocked without emptying the trolley."""
    cart = FakeCart()
    with pytest.raises(CartError) as e: cart.add('caviar')
    assert 'Full Cream Milk 2L' in str(e.value)        # the real options, not a guess

    cart.find('milk')
    assert cart.add(0)['item']['title'] == 'Full Cream Milk 2L'
    with pytest.raises(CartError): cart.add(3)         # that page has one row, not the whole store
    assert cart.add('Sourdough Loaf 680g')['ok']       # a title survives a narrower search

    moved = FakeCart()
    moved.add('milk')
    moved.open('https://members.ceresfairfood.org.au')
    assert not moved.find('milk')
    assert moved.add('Seasonal Fruit Box - Medium')['ok']
    assert moved.total() == {'count': 2, 'subtotal': '$42.60'}


def test_a_bad_add_is_reported_and_spending_money_is_gated_like_a_write():
    ts = {t.__name__: t for t in cart_tools(FakeCart())}
    out = ts['cart_add']('caviar')
    assert failed(out) and out.startswith(ERR + "could not add 'caviar'"), out
    assert 'no products matching' in ts['cart_find']('caviar')
    assert {'cart_add', 'cart_remove'} <= WRITE_TOOLS
    assert 'cart_find' not in WRITE_TOOLS
