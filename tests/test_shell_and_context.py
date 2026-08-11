"""The surface that came back from leela when ramabana became the shared agent core.

Running a command, exact-text editing, literal search, the `ERROR:` convention, and the
project's own `AGENTS.md`. None of it had a test in either repository before the merge.
"""
from ramabana import agent as A
from ramabana import tools
from ramabana.testing import MemHost, fake_agent
from ramabana.tools import (ERR, LocalHost, NullHost, code_tools, failed, file_tools,
                            shell_tools, tools_for)


def names(ts): return {t.__name__ for t in ts}


def by_name(ts): return {t.__name__: t for t in ts}


# -- running a command -------------------------------------------------------

def test_a_host_that_cannot_run_commands_is_not_offered_the_shell_tool():
    "`run_cmd` has no harmless probe, so `_supports` asks whether the host overrode it."
    assert 'run_shell' not in names(tools_for(NullHost()))
    assert 'run_shell' in names(tools_for(MemHost()))


def test_the_capability_probe_never_spawns_anything():
    h = MemHost()
    tools_for(h)
    assert h.cmds == []                     # the empty command is a no-op, by contract


def test_a_failing_command_is_a_result_the_model_can_read():
    h = MemHost(commands={'pytest': (1, 'E   assert 1 == 2')})
    run = by_name(shell_tools(h))['run_shell']
    out = run('pytest')
    assert failed(out) and 'exit 1' in out and 'command FAILED' in out
    assert 'assert 1 == 2' in out
    assert h.cmds == [('pytest', None, 120)]


def test_a_passing_command_is_not_marked_as_a_failure():
    out = by_name(shell_tools(MemHost(commands={'true': (0, 'ok')})))['run_shell']('true')
    assert not failed(out) and out.startswith('exit 0')


def test_an_empty_command_is_refused_rather_than_run():
    h = MemHost()
    assert failed(by_name(shell_tools(h))['run_shell']('  '))
    assert h.cmds == []


# -- the one spelling of failure ---------------------------------------------

def test_every_tool_failure_is_spelled_the_same_way():
    "The activity feed and `Agent.problems` read this prefix; a tool that invents its own is invisible."
    fs = by_name(file_tools(MemHost()))
    assert failed(fs['view_file']('nope.py'))
    assert failed(fs['edit_file']('a.py', 'not json'))
    assert failed(fs['replace_text']('a.py', '[]'))
    assert tools.err('x') == ERR + 'x'
    assert failed(ERR + 'anything') and not failed('a normal result')


def test_a_lost_capability_ends_the_tool_call_not_the_turn():
    "A kernel dies mid-session. The model should read a failure, not have its turn raise."
    a, be = fake_agent()
    def gone(): raise NotImplementedError('kernel is gone')
    gone.__name__ = 'list_vars'
    out = a._record(gone)()
    assert failed(out) and 'list_vars is not available here' in out


# -- exact-text editing ------------------------------------------------------

def test_replace_text_writes_only_when_every_edit_located():
    h = MemHost({'/proj/a.py': 'def a():\n    return 1\n'})
    rt = by_name(file_tools(h))['replace_text']
    out = rt('a.py', '[{"oldText": "return 1", "newText": "return 2"},'
                     ' {"oldText": "def a():", "newText": "def b():"}]')
    assert not failed(out)
    assert h.files['/proj/a.py'] == 'def b():\n    return 2\n'


def test_an_ambiguous_or_stale_edit_leaves_the_file_alone():
    before = 'x = 1\nx = 1\n'
    h = MemHost({'/proj/a.py': before})
    rt = by_name(file_tools(h))['replace_text']
    assert failed(rt('a.py', '[{"oldText": "x = 1", "newText": "x = 2"}]'))
    assert failed(rt('a.py', '[{"oldText": "y = 9", "newText": "y = 8"}]'))
    assert h.files['/proj/a.py'] == before


def test_the_three_shapes_a_model_actually_sends_are_all_accepted():
    for edits in ('[["a", "b"]]', [{'oldText': 'a', 'newText': 'b'}], {'oldText': 'a', 'newText': 'b'}):
        h = MemHost({'/proj/f.txt': 'a\n'})
        assert not failed(by_name(file_tools(h))['replace_text']('f.txt', edits))
        assert h.files['/proj/f.txt'] == 'b\n'


# -- literal search ----------------------------------------------------------

def test_grep_finds_every_literal_occurrence():
    h = MemHost({'/proj/a.py': 'import os\nos.getcwd()\n', '/proj/b.py': 'import sys\n'})
    g = by_name(code_tools(h))['grep']
    out = g('import')
    assert '/proj/a.py:1' in out and '/proj/b.py:1' in out
    assert '2 match(es) in 2 file(s)' in out
    assert 'no matches' in g('nothing_here')
    assert '/proj/a.py' in g('import', path_filter='a.py') and '/proj/b.py' not in g('import', path_filter='a.py')


def test_grep_refuses_a_pattern_it_cannot_compile():
    assert failed(by_name(code_tools(MemHost()))['grep']('('))
    assert failed(by_name(code_tools(MemHost()))['grep'](''))
    # …unless the model meant it literally
    h = MemHost({'/proj/a.py': 'f(\n'})
    assert '/proj/a.py:1' in by_name(code_tools(h))['grep']('(', regex=False)


# -- the briefing ------------------------------------------------------------

def test_a_rule_for_a_tool_the_host_lacks_is_not_advertised():
    "A rule about `run_shell` on a host that cannot run commands costs the model a wasted turn."
    assert 'run_shell' in A.work_rules(['run_shell'])
    assert 'run_shell' not in A.work_rules(['view_file'])
    assert 'run_shell' in A.work_rules()          # no filter means the whole thing


def test_the_briefing_is_built_from_the_tools_the_model_is_given():
    h = MemHost()
    sp = A.system_prompt(h, tools=tools_for(h))
    for t in names(tools_for(h)) & {n for n, _ in A.RULES if n}: assert t in sp
    assert 'delegate_parallel' not in sp          # this host offers no subagents


def test_the_project_s_own_instructions_are_read_and_marked_as_its_own():
    h = MemHost({'/proj/AGENTS.md': 'Use uv, never pip.'})
    ctx = A.project_context(h)
    assert 'Use uv, never pip.' in ctx
    assert 'path="/proj/AGENTS.md"' in ctx       # so the model can go read the file itself
    assert A.project_context(MemHost()) == ''


def test_a_documentation_sized_agents_md_is_truncated_not_dropped():
    h = MemHost({'/proj/AGENTS.md': 'x' * (A.MAX_CONTEXT_FILE + 500)})
    ctx = A.project_context(h)
    assert 'truncated' in ctx and len(ctx) < A.MAX_CONTEXT_FILE + 800


def test_project_instructions_reach_the_system_prompt():
    h = MemHost({'/proj/AGENTS.md': 'Run the tests with `nbdev-test`.'})
    assert 'nbdev-test' in A.system_prompt(h, tools=tools_for(h))


# -- the reference host can run commands too ---------------------------------

def test_the_local_host_offers_the_shell_tool(tmp_path):
    "A terminal or MCP agent that can edit but not run has no way to check its own work."
    h = LocalHost([str(tmp_path)], web=False, index=False)
    assert 'run_shell' in names(tools_for(h))
    assert h.run_cmd('') == (0, '')                    # the probe spawns nothing
    code, out = h.run_cmd('echo hello')
    assert code == 0 and 'hello' in out


def test_the_local_host_interleaves_the_streams_and_reports_the_code(tmp_path):
    h = LocalHost([str(tmp_path)], web=False, index=False)
    code, out = h.run_cmd('echo first; echo second 1>&2; exit 3')
    assert code == 3 and out.splitlines() == ['first', 'second']


def test_a_hung_command_is_killed_rather_than_kept(tmp_path):
    h = LocalHost([str(tmp_path)], web=False, index=False)
    code, out = h.run_cmd('sleep 30', timeout=1)
    assert code == 124 and 'killed after 1s' in out


def test_a_command_cannot_be_started_outside_the_open_folders(tmp_path):
    import pytest
    from ramabana.core import AgentError
    h = LocalHost([str(tmp_path / 'inside')], web=False, index=False)
    (tmp_path / 'inside').mkdir()
    with pytest.raises(AgentError): h.run_cmd('pwd', cwd=str(tmp_path / 'outside'))
