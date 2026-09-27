"""The MCP client: a real server over stdio for the wire, plus the annotation logic that decides
whether a wrapped tool is gated as a write.
"""
import json
import sys
from pathlib import Path

import pytest
from shalya.core import is_write

from ramabana.mcpclient import MCPLoop, _connect, _stdio_env, _tool_hints, _wrap, acp_mcp_spec, mcp_config, mcp_tools
from ramabana.testing import fake_agent

HERE = Path(__file__).parent


def test_acp_mcp_spec_converts_stdio_and_http_servers_the_editor_named():
    stdio = type('S', (), {'command': 'npx', 'args': ['-y', 'weather'], 'env': [
        type('E', (), {'name': 'KEY', 'value': 'k'})()], 'name': 'weather'})()
    assert acp_mcp_spec(stdio) == ('weather', {'command': ['npx', '-y', 'weather'], 'env': {'KEY': 'k'}})

    http = type('S', (), {'url': 'https://mcp.example', 'name': 'remote', 'headers': [
        type('H', (), {'name': 'Authorization', 'value': 'Bearer tok123'})()]})()
    assert acp_mcp_spec(http) == ('remote', {'url': 'https://mcp.example', 'token': 'tok123'})

    bare = type('S', (), {'url': 'https://open.example', 'name': 'open', 'headers': []})()
    assert acp_mcp_spec(bare) == ('open', {'url': 'https://open.example', 'token': None})


def test_mcp_config_merges_extra_project_and_cfg_by_priority(tmp_path):
    (tmp_path/'mcp.json').write_text(json.dumps({'servers': {'a': {'url': 'https://cfg'}, 'b': {'url': 'https://cfg-b'}}}))
    project = tmp_path/'proj'/'.agents'
    project.mkdir(parents=True)
    (project/'mcp.json').write_text(json.dumps({'servers': {'a': {'url': 'https://project'}}}))

    # a project's own mcp.json runs whatever command it names, so it needs the same opt-in as project extensions
    without_opt_in = mcp_config(tmp_path, [tmp_path/'proj'])
    assert without_opt_in == {'a': {'url': 'https://cfg'}, 'b': {'url': 'https://cfg-b'}}, \
        'the project file must not be read without project=True'

    found = mcp_config(tmp_path, [tmp_path/'proj'], extra={'a': {'url': 'https://extra'}}, project=True)
    assert found == {'a': {'url': 'https://extra'}, 'b': {'url': 'https://cfg-b'}}


@pytest.mark.slow   # spawns a real subprocess
def test_a_real_stdio_server_round_trips_a_call_and_defaults_to_a_write():
    loop = MCPLoop()
    try:
        client, hints = _connect({'command': [sys.executable, str(HERE/'mcp_serve.py')]}, loop)
        try:
            assert hints == {'add': {}}
            add = _wrap(client, 'add', hints, loop)
            assert add(a=2, b=3) == '5'
            assert is_write(add), 'no annotation at all defaults to gated, not trusted'
        finally:
            loop.run(client.tr.aclose())
    finally:
        loop.close()


@pytest.mark.slow   # spawns a real subprocess
def test_an_agent_wires_a_server_named_at_construction_into_its_own_tools(tmp_path):
    a, _ = fake_agent(cfg=tmp_path,
                      mcp_servers={'test': {'command': [sys.executable, str(HERE/'mcp_serve.py')]}})
    try:
        names = {t.__name__ for t in a.tools}
        assert 'add' in names
        add = next(t for t in a.tools if t.__name__ == 'add')
        assert add(a=4, b=5) == '9' and is_write(add)
    finally:
        a.close()


def test_stdio_env_adds_to_the_parent_environment_rather_than_replacing_it():
    import os
    assert _stdio_env(None) is None
    assert _stdio_env({}) is None
    merged = _stdio_env({'MY_KEY': 'v'})
    assert merged['MY_KEY'] == 'v'
    assert merged.get('PATH') == os.environ.get('PATH'), 'a configured env must not drop the parent PATH'


def test_readonlyhint_must_be_the_literal_true_not_merely_truthy():
    import inspect
    def f(): pass
    f.__signature__ = inspect.signature(f)
    class FakeClient: tools = {'f': f}

    call = _wrap(FakeClient(), 'f', {'f': {'readOnlyHint': 'false'}}, loop=None)
    assert is_write(call), 'the string "false" is truthy in Python and must still be gated'

    call2 = _wrap(FakeClient(), 'f', {'f': {'readOnlyHint': True}}, loop=None)
    assert not is_write(call2)


def test_a_non_dict_annotations_value_from_a_malformed_server_is_ignored_not_fatal():
    raw = [{'name': 'f', 'annotations': ['not', 'a', 'dict']}, {'name': 'g'}, {'name': 'h', 'annotations': None}]
    assert _tool_hints(raw) == {'f': {}, 'g': {}, 'h': {}}


def test_mcp_tools_skips_a_server_that_cannot_connect_rather_than_failing():
    seen = []
    tools, loop, clients = mcp_tools(None, [], extra={'broken': {'command': ['nope-not-a-real-command']}},
                                     on_error=lambda name, e: seen.append(name))
    try:
        assert tools == [] and clients == [] and seen == ['broken']
    finally:
        if loop is not None: loop.close()
