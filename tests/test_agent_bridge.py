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
from ramabana.runtime import CHAT_CALLBACKS, TokenLogger, Usage
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


def test_an_unknown_operation_says_so_rather_than_hanging_or_500ing():
    bridge, _ = a_bridge()

    async def scenario():
        url = await bridge.start()
        try:
            for query in ('op=nonsense', 'op=', 'op=attach_callback'):
                with pytest.raises(HTTPError) as e: get(url, bridge.token, query=query)
                assert e.value.code == 400
                assert json.load(e.value).get('error'), 'a refusal has to say what was wrong'
        finally: await bridge.close()
    asyncio.run(scenario())


def test_closing_a_bridge_that_never_started_is_not_an_error():
    "`close` read `self.thread`, which `__init__` never set."
    bridge, _ = a_bridge()
    assert bridge.thread is None
    asyncio.run(bridge.close())
    asyncio.run(bridge.close())


def test_a_usage_field_the_counter_does_not_carry_reads_as_absent():
    "A bare `getattr` turned a counter of another shape into an opaque 400."
    bridge, agent = a_bridge()

    class Thin:
        total = 7
    agent.use = Thin()
    assert bridge.call('usage') == {**{k: None for k in AgentBridge.FIELDS}, 'total': 7}


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


def test_asking_for_one_callback_does_not_attach_the_whole_catalogue():
    """The registry was seeded with every known callback, and `_be` applies the whole registry to a
    chat it builds -- so asking for one attached all of them. It holds what was asked for."""
    agent, _ = fake_agent()
    known = dict(CHAT_CALLBACKS)
    CHAT_CALLBACKS['a_second_one'] = TokenLogger
    try:
        attached = []
        agent._be = lambda job='turn': type('B', (), {'add_cb': lambda _s, cb: attached.append(cb)})()
        assert agent.add_chat_callback('a_second_one') == 'a_second_one'
        assert sorted(agent._chat_callbacks) == ['a_second_one'], 'only what was asked for'
        assert len(attached) == 1
        assert agent.add_chat_callback('a_second_one') == 'a_second_one'
        assert len(attached) == 1, 'asking twice attaches once'
    finally: CHAT_CALLBACKS.clear(); CHAT_CALLBACKS.update(known)


def test_an_unknown_callback_names_what_there_is_and_registers_nothing():
    agent, _ = fake_agent()
    with pytest.raises(KeyError) as e: agent.add_chat_callback('token_loggr')
    assert 'token_logger' in str(e.value), 'a near miss should name the real one'
    assert not getattr(agent, '_chat_callbacks', {}), 'a refusal registers nothing'


def test_the_usage_logger_writes_to_its_sink_rather_than_over_the_terminal():
    """`print` from a chat callback fires on the turn thread and lands between the compositor's
    rows, which repaints the transcript around it. A surface that owns a screen sets `sink`."""
    class Use:
        model, prompt_tokens, completion_tokens = 'm', 1, 2
        total_tokens, cached_tokens, cost = 3, 0, 0.5
    cb = TokenLogger()
    cb.chat = type('C', (), {'use': Use()})()
    held, before = [], TokenLogger.sink
    TokenLogger.sink = held.append
    try:
        cb.after_response()
        assert len(held) == 1 and 'model=m' in held[0] and 'cost=$0.500000' in held[0]
        Use.cost = None                       # a provider is allowed to report null
        cb.after_response()
        assert 'cost=$0.000000' in held[1], 'a null cost must not raise inside a turn'
        Use.model = None
        cb.after_response()
        assert 'model=?' in held[2]
    finally: TokenLogger.sink = before


def test_the_usage_logger_still_prints_when_nothing_claimed_the_sink(capsys):
    "Unset means `print`, which is right in a plain REPL."
    class Use:
        model, prompt_tokens, completion_tokens = 'm', 1, 2
        total_tokens, cached_tokens, cost = 3, 0, 0.
    cb = TokenLogger()
    cb.chat = type('C', (), {'use': Use()})()
    before, TokenLogger.sink = TokenLogger.sink, None
    try:
        cb.after_response()
        assert '[rishi usage] model=m' in capsys.readouterr().out
    finally: TokenLogger.sink = before


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


def test_a_callback_registered_while_idle_takes_effect_at_once():
    from ramabana.runtime import Backend, TokenLogger
    from ramabana.testing import SPEC

    class Chat:
        def __init__(self): self.cbs = []
        def add_cb(self, cb): self.cbs.append(cb() if isinstance(cb, type) else cb)

    class Fake(Backend):
        def _start(self): return Chat()

    backend = Fake(SPEC)
    backend.start()
    backend.add_cb(TokenLogger)
    assert len(backend.chat.cbs) == 1
    backend.retry()                              # a replacement chat gets it too
    assert len(backend.chat.cbs) == 1


def test_a_mutation_is_run_where_the_agent_lives():
    """Reading a counter from a handler thread is harmless; attaching a callback can build a backend
    and reach into a live chat. It goes through the owner's dispatcher and the result comes back."""
    import threading
    agent, _ = fake_agent()
    seen = []
    agent._be = lambda job='turn': type('B', (), {'add_cb': lambda _s, cb: None})()

    def dispatch(work):
        seen.append(threading.current_thread().name)
        return work()

    bridge = AgentBridge(agent, dispatch=dispatch)

    async def scenario():
        url = await bridge.start()
        try:
            body = get(url, bridge.token, query='op=attach_callback&name=token_logger')
            assert body['result'] == 'token_logger'
            assert len(seen) == 1, 'the mutation was dispatched, not run on the handler thread'
            assert get(url, bridge.token)['result'] is not None
            assert len(seen) == 1, 'and a read was not'
        finally: await bridge.close()
    asyncio.run(scenario())


def test_a_dispatcher_that_refuses_is_reported_rather_than_swallowed():
    "A loop stuck inside a turn raises, and the caller is told instead of waiting forever."
    agent, _ = fake_agent()

    def dispatch(work): raise TimeoutError('the agent is busy')
    bridge = AgentBridge(agent, dispatch=dispatch)

    async def scenario():
        url = await bridge.start()
        try:
            with pytest.raises(HTTPError) as e:
                get(url, bridge.token, query='op=attach_callback&name=token_logger')
            assert e.value.code == 400 and 'busy' in json.load(e.value)['error']
        finally: await bridge.close()
    asyncio.run(scenario())

