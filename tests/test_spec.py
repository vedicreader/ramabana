"""Calling a described API with the caller's own key, and resolving the operation to call.

Nothing here reaches the network. `_client` is the seam fastspec sits behind, so the double
records which headers reached which spec, and the assertions are about that.
"""

from ramabana.spec import SpecHost


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


def test_and_no_further_than_that():
    "One host holds many specs; an unguarded `headers` would send stripe's key to github."
    h = host(creds={'stripe': {'Authorization': 'Bearer sk_live_1'}})
    h.api_call('get_balance', name='stripe')
    h.api_call('list_repos', name='github')
    assert 'Authorization' not in h._clients['github'].headers
    assert h.headers == {}


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
