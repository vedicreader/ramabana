"""Calling a described API with the caller's own key, and resolving the operation to call.

Nothing here reaches the network. `_client` is the seam fastspec sits behind, so the double
records which headers reached which spec, and the assertions are about that.
"""

import pytest

from ramabana.spec import SpecHost, SpecError


class FakeClient:
    "What fastspec builds: operations as attributes, and the headers it was constructed with."
    def __init__(self, headers): self.headers, self.calls = dict(headers), []
    def get_balance(self, **kw): self.calls.append(('get_balance', kw)); return {'ok': 'get_balance'}
    def list_repos(self, **kw): self.calls.append(('list_repos', kw)); return {'ok': 'list_repos'}


class Host(SpecHost):
    "A `SpecHost` with fastspec's client swapped for a double that remembers its headers."
    def _client(self, key, parsed):
        if key not in self._clients:
            self._clients[key] = FakeClient({**self.headers, **self._creds.get(key, {})})
        return self._clients[key]


def host(**kw): return Host(roots=['.'], specs={'stripe': object(), 'github': object()}, **kw)


def test_a_key_reaches_the_spec_it_belongs_to():
    h = host(creds={'stripe': {'Authorization': 'Bearer sk_live_1'}})
    h.api_call('get_balance', name='stripe')
    assert h._clients['stripe'].headers['Authorization'] == 'Bearer sk_live_1'


def test_and_no_further_than_that():
    "One host holds many specs; an unguarded `headers` would send stripe's key to github."
    h = host(creds={'stripe': {'Authorization': 'Bearer sk_live_1'}})
    h.api_call('get_balance', name='stripe')
    h.api_call('list_repos', name='github')
    assert 'Authorization' not in h._clients['github'].headers
    assert h.headers == {}


def test_the_host_wide_headers_still_reach_every_spec():
    "`headers` is what every call carries; `creds` is what one spec adds to it."
    h = host(headers={'User-Agent': 'ramabana'}, creds={'stripe': {'X-Api-Key': 'k'}})
    h.api_call('list_repos', name='github')
    assert h._clients['github'].headers == {'User-Agent': 'ramabana'}


def test_a_call_with_no_credentials_still_goes_out():
    "Unauthenticated is a 401 from the API, which is an answer; refusing here would not be."
    assert host().api_call('get_balance', name='stripe') == {'ok': 'get_balance'}


def test_changing_a_key_drops_the_client_that_captured_the_old_one():
    h = host(creds={'stripe': {'Authorization': 'Bearer old'}})
    h.api_call('get_balance', name='stripe')
    h.api_creds('stripe', {'Authorization': 'Bearer new'})
    assert 'stripe' not in h._clients
    h.api_call('get_balance', name='stripe')
    assert h._clients['stripe'].headers['Authorization'] == 'Bearer new'


def test_clearing_a_key_leaves_the_spec_callable():
    h = host(creds={'stripe': {'Authorization': 'Bearer old'}})
    assert h.api_creds('stripe', None) == []
    h.api_call('get_balance', name='stripe')
    assert 'Authorization' not in h._clients['stripe'].headers


def test_what_is_reported_is_header_names_and_never_values():
    h = host(creds={'stripe': {'Authorization': 'Bearer sk_live_1', 'X-Api-Key': 'k'}})
    assert h.api_keyed() == {'stripe': ['Authorization', 'X-Api-Key']}


def test_an_operation_named_after_its_group_is_still_callable():
    """fastspec names a group after a path segment, so `/v1/latest` makes a group `latest` too.

    Taking the first matching attribute then finds the group, and calling it raises
    `'OpGroup' object is not callable`.
    """
    class Grouped(Host):
        def _client(self, key, parsed):
            c = FakeClient({})
            c.latest = type('OpGroup', (), {'latest': staticmethod(lambda **kw: {'ok': 'latest'})})()
            return c
    h = Grouped(roots=['.'], specs={'rates': object()})
    assert h.api_call('latest', name='rates') == {'ok': 'latest'}


def test_and_an_operation_that_is_nowhere_is_an_error_naming_the_spec():
    with pytest.raises(SpecError, match='no operation'): host().api_call('nope', name='stripe')
