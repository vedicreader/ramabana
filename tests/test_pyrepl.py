"""Pyrepl feature block: CLI flags and the Dhrishti overlay contract.

Notebook `11_pyrepl.ipynb` owns the readable kernel/overlay examples; this file covers the
CLI seam and one end-to-end overlay property pytest can assert without nbdev-test.
"""

import asyncio

import pytest

from ramabana import cli
from ramabana.pyrepl import DhrishtiHost, Kernel, output_text

pytest.importorskip('dhrishti', reason='pip install ramabana[pyrepl]')


def test_cli_python_mode_and_output_text():
    "One command exposes `--python` / `--attach` / `--spec`; jupyter outputs normalise to text."
    from fastcore.script import anno_parser
    p = anno_parser(cli.main.__wrapped__, pos=['prompt'])
    assert p.parse_args(['--python']).python is True
    assert p.parse_args(['--attach', 'proj']).attach == 'proj'
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
            owner = await kernel.execute('owner_value')
            assert output_text(owner.outputs) == '40'
        finally:
            await kernel.shutdown()
    asyncio.run(scenario())
