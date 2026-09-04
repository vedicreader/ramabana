"""Pyrepl feature block: CLI flags and the Dhrishti overlay contract.

Notebook `11_pyrepl.ipynb` owns the readable kernel/overlay examples; this file covers the
CLI seam and one end-to-end overlay property pytest can assert without nbdev-test.
"""

import asyncio

import pytest

from ramabana import cli
from ramabana.pyrepl import (AgentBridge, DhrishtiHost, Kernel, agent_proxy_code,
                             inject_agent_proxy, output_text)

pytest.importorskip('dhrishti', reason='pip install dhrishti')


def test_cli_python_mode_and_output_text():
    "One command exposes `--python` / `--attach` / `--spec`; jupyter outputs normalise to text."
    from fastcore.script import anno_parser
    p = anno_parser(cli.main.__wrapped__, pos=['prompt'])
    assert p.parse_args(['--python']).python is True
    assert p.parse_args(['--attach', 'proj']).attach == 'proj'
    # fastcore spells a flag with hyphens and binds it to the underscored name
    assert p.parse_args(['--agent-proxy']).agent_proxy is True
    assert p.parse_args(['--pii-ner']).pii_ner is True
    assert 'agent_proxy' in cli.SURFACE_COMMANDS
    assert p.parse_args(['--spec']).spec is True
    assert p.parse_args([]).python is False
    assert p.parse_args(['one question']).prompt == 'one question'

    outputs = [
        {'output_type': 'stream', 'text': 'hello\n'},
        {'output_type': 'execute_result', 'data': {'text/plain': '42'}},
        {'output_type': 'error', 'ename': 'ValueError', 'evalue': 'bad', 'traceback': []},
    ]
    assert output_text(outputs) == 'hello\n42\nValueError: bad'


def test_dhrishti_overlay_reads_without_rebinding_owner(tmp_path):
    "Agent overlay can read owner names and shadow them without mutating the owner namespace."
    async def scenario():
        kernel = Kernel(cwd=tmp_path)
        await kernel.start()
        try:
            result = await kernel.execute('owner_value = 40')
            assert result.ok
            host = DhrishtiHost([tmp_path], kernel.base, web=False, index=False)
            host.log_cell('owner_value = 40', result.outputs)
            assert host.run_python('agent_value = owner_value + 2') == '(ok)'
            assert 'agent_value' in host.list_vars() and host.agent_log.exists()
            from fastcore.nbio import read_nb
            assert read_nb(host.agent_log).cells[0].outputs == result.outputs
            assert host.run_python('owner_value = 0') == '(ok)'
            from ramabana.testing import fake_agent
            from ramabana.runtime import Usage
            agent, _ = fake_agent()
            agent.use = Usage(model='test', total=24, cost=0.0031)
            bridge = AgentBridge(agent)
            try:
                assert inject_agent_proxy(host, await bridge.start(), bridge.token) == '(ok)'
                assert host.run_python('ramabana_agent.usage()["cost"]') == '0.0031'
            finally: await bridge.close()
            owner = await kernel.execute('owner_value')
            assert output_text(owner.outputs) == '40'
        finally:
            await kernel.shutdown()
    asyncio.run(scenario())


def test_agent_callback_is_attached_once_and_reapplied_to_a_retried_chat():
    from ramabana.runtime import Backend
    from ramabana.testing import fake_agent

    class Chat:
        def __init__(self): self.cbs = []
        def add_cb(self, cb):
            cb = cb() if isinstance(cb, type) else cb
            cb.chat = self
            self.cbs.append(cb)
            return cb

    class CallbackBackend(Backend):
        def _start(self): return Chat()

    agent, _ = fake_agent()
    spec = agent.routing.spec('turn')
    backend = CallbackBackend(spec)
    backend.start()
    agent._backends[(spec.backend, spec.model_id)] = backend
    agent._be = lambda job='turn': backend
    bridge = AgentBridge(agent)
    assert bridge.call('attach_callback', 'token_logger') == 'token_logger'
    assert len(backend.chat.cbs) == 1
    backend.retry()
    assert len(backend.chat.cbs) == 1


def test_agent_bridge_reports_usage_and_requires_its_token():
    "The PyREPL proxy only reaches the owner agent through its bearer-token bridge."
    from ramabana.testing import fake_agent
    from urllib.error import HTTPError
    from urllib.request import urlopen

    from ramabana.runtime import Usage

    agent, backend = fake_agent(replies=['ok'])
    agent.use = Usage(model='test', input=20, output=4, total=24, cost=0.0031)

    async def scenario():
        bridge = AgentBridge(agent)
        url = await bridge.start()
        try:
            assert bridge.call('usage')['cost'] == pytest.approx(0.0031)
            with pytest.raises(HTTPError) as error: urlopen(url + '/agent?op=usage')
            assert error.value.code == 401
        finally: await bridge.close()
    asyncio.run(scenario())


def test_the_proxy_reaches_the_prompt_and_carries_between_sessions(tmp_path):
    """The overlay and the prompt are different namespaces. Binding only in the overlay -- what an
    agent's own Python tools see -- left `ramabana_agent` a `NameError` at the prompt a person types
    at, under a message saying it was ready. And because a second session attached to this kernel
    binds into the same two namespaces, that is also how it hands its agent over: both proxies sit
    in `ramabana_agents`, and a cell can attach a callback to either one."""
    from ramabana.runtime import Usage
    from ramabana.testing import fake_agent

    async def scenario():
        kernel = await Kernel(tmp_path).start()
        host = DhrishtiHost([str(tmp_path)], kernel.base)
        mine, _ = fake_agent(); mine.use = Usage(model='mine', total=24, cost=0.0031)
        yours, _ = fake_agent(); yours.use = Usage(model='yours', total=99, cost=0.5)
        ours = (AgentBridge(mine), AgentBridge(yours))
        try:
            for bridge, label in zip(ours, ('sessA', 'sessB')):
                url = await bridge.start()
                assert inject_agent_proxy(host, url, bridge.token, label) == '(ok)'
                held = await kernel.execute(agent_proxy_code(url, bridge.token, label))
                assert held.ok, output_text(held.outputs)

            async def cell(code):
                out = await kernel.execute(code)
                assert out.ok, output_text(out.outputs)
                return output_text(out.outputs)

            assert await cell('sorted(ramabana_agents)') == "['sessA', 'sessB']"
            assert await cell('ramabana_agent.label') == "'sessB'", 'the bare name is the last bound'
            assert await cell('ramabana_agents["sessA"].usage()["model"]') == "'mine'"
            assert await cell('ramabana_agents["sessB"].usage()["model"]') == "'yours'"
            # the point of the feature: a cell attaches a callback to the other session's agent
            assert await cell('ramabana_agents["sessA"].attach_callback("token_logger")') == "'token_logger'"
            assert sorted(mine._chat_callbacks) == ['token_logger']
            assert not getattr(yours, '_chat_callbacks', {}), 'and leaves the other alone'
            assert 'token_logger' in await cell('ramabana_agents["sessA"].callbacks()["attached"]')
            # a refusal crosses the wire as a refusal, not as a hang or a blank
            bad = await kernel.execute('ramabana_agents["sessA"].attach_callback("nope")')
            assert not bad.ok and 'unknown callback' in output_text(bad.outputs)
            # the overlay holds the same two, which is what an attached agent reads
            assert host.run_python('sorted(ramabana_agents)') == "['sessA', 'sessB']"
        finally:
            for bridge in ours: await bridge.close()
            await kernel.shutdown()
    asyncio.run(scenario())


def test_a_kernel_that_never_started_binds_nothing_and_opens_no_socket():
    """`enter_python` can fail two ways -- the pyrepl extras missing, or the kernel refusing to
    start -- and it notes which. Carrying on from there opened a listening socket and bound the
    proxy into whatever host was still in place, then reported it ready."""
    from ramabana.testing import fake_agent

    agent, _ = fake_agent()
    ui = cli.Ui.__new__(cli.Ui)
    ui.agent, ui.kernel, ui.attached = agent, None, ''
    ui.agent_bridge, ui.proxy_url, ui.loop = None, '', None
    ui.notes = []
    ui.note = lambda text, kind='note': ui.notes.append(text)
    async def no_kernel(): ui.notes.append('no kernel: refused')
    ui.enter_python = no_kernel

    assert asyncio.run(cli.Ui.enable_agent_proxy(ui)) is None
    assert ui.agent_bridge is None, 'no bridge, so no socket left listening'
    assert ui.notes == ['no kernel: refused'], 'and nothing claimed it was ready'

