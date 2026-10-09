"""The trolley: `fossick.shop` behind a small interface, and what it does when an add cannot land.

Its own block because it is its own subject. What the notebooks do not show is the failure shape,
which is the whole reason the interface exists: a model that asked for caviar should learn what
the store actually stocks rather than have its turn end.
"""
import pytest

from ramabana.shop import CartError, FakeCart


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


