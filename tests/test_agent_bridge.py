"""The loopback bridge that lets Python reach an agent, and the callbacks it can attach.

One session exposes its agent over `127.0.0.1` behind a bearer token; a cell in a kernel holds a
proxy and calls it. Nothing here starts a kernel or loads a model, so none of it needs dhrishti.
"""
import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ramabana.pyrepl import AgentBridge, agent_proxy_code
from ramabana.runtime import Usage
from ramabana.testing import fake_agent


def a_bridge(**use):
    agent, _ = fake_agent()
    agent.use = Usage(**use) if use else agent.use
    return AgentBridge(agent), agent


def get(url, token=None, path='/agent', query='op=usage'):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    with urlopen(Request(f'{url}{path}?{query}', headers=headers)) as r: return json.load(r)


def test_the_token_is_the_whole_boundary_and_a_wrong_one_is_refused():
    """Only a missing token was covered, and a wrong one takes a different path through the
    handler. A mistyped path used to answer 401, which says `your token is wrong` about something
    that was never an auth question."""
    bridge, _ = a_bridge(model='test', total=24, cost=0.0031)

    async def scenario():
        url = await bridge.start()
        try:
            assert get(url, bridge.token)['result']['cost'] == pytest.approx(0.0031)
            for bad in (None, 'not-the-token', bridge.token[:-1], bridge.token + 'x'):
                with pytest.raises(HTTPError) as e: get(url, bad)
                assert e.value.code == 401, f'{bad!r} was accepted'
            with pytest.raises(HTTPError) as e: get(url, bridge.token, path='/nope')
            assert e.value.code == 404, 'a wrong path is not an auth failure'
        finally: await bridge.close()
    asyncio.run(scenario())


def test_the_proxy_source_rebinds_the_agent_without_redefining_its_class():
    "Two sessions binding into one namespace must not have the second redefine the first's class."
    space = {}
    exec(agent_proxy_code('http://127.0.0.1:1', 'ta', 'sessA'), space)
    first = space['AgentProxy']
    exec(agent_proxy_code('http://127.0.0.1:2', 'tb', 'sessB'), space)
    assert sorted(space['ramabana_agents']) == ['sessA', 'sessB']
    assert space['ramabana_agent'].label == 'sessB', 'the bare name is whoever bound last'
    assert isinstance(space['ramabana_agents']['sessA'], first), 'sessA kept its class'
    assert repr(space['ramabana_agents']['sessA']) == "AgentProxy('sessA')"


def test_a_callback_registered_during_a_turn_lands_at_the_turn_boundary():
    """`chat.cbs` is a list Rishi walks while a turn runs, and `Backend.lock` is held for the whole
    of that turn. A caller on another thread used to splice straight into it. It records instead,
    and the turn takes it up where it already synchronises."""
    import threading
    from ramabana.runtime import Backend, TokenLogger
    from ramabana.testing import SPEC

    class Chat:
        def __init__(self): self.cbs = []
        def add_cb(self, cb):
            cb = cb() if isinstance(cb, type) else cb
            self.cbs.append(cb); return cb

    class Fake(Backend):
        def _start(self): return Chat()
        def _send(self, msg, **kw): return 'done'
        def _usage(self): return self.use

    backend = Fake(SPEC)
    backend.start()
    backend.lock.acquire()                       # stand in for a turn in flight
    try:
        backend.add_cb(TokenLogger)
        assert backend._callbacks == [TokenLogger], 'recorded'
        assert backend.chat.cbs == [], 'and not spliced into the turn that is running'
    finally: backend.lock.release()
    backend.send('hello')                        # the next turn is the boundary
    assert len(backend.chat.cbs) == 1
    backend.send('again')
    assert len(backend.chat.cbs) == 1, 'and it is not added twice'
