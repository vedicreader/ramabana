"""Pyrepl feature block: CLI flags and the Dhrishti overlay contract.

Notebook `11_pyrepl.ipynb` owns the readable kernel/overlay examples; this file covers the
CLI seam and one end-to-end overlay property pytest can assert without nbdev-test.
"""

import asyncio

import pytest

from ramabana.pyrepl import (AgentBridge, DhrishtiHost, Kernel, agent_proxy_code,
                             inject_agent_proxy, output_text)

pytest.importorskip('dhrishti', reason='pip install dhrishti')


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
