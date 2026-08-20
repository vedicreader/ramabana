"""The tools themselves: which ones a host earns, what they return, and where they may reach.

One functional block, gathered from `test_shell_and_context.py` and the sandbox half of
`test_harness.py`. The briefing that describes these tools is a different block and lives in
`test_briefing.py`; what is here is the tools' own behaviour.

Most of this surface came back from leela when ramabana became the shared agent core, and none of
it had a test in either repository before the move.
"""
import pytest

from ramabana import core, tools
from ramabana.testing import MemHost, fake_agent
from ramabana.core import AgentError
from ramabana.tools import (ERR, LocalHost, NullHost, code_tools, failed, file_tools,
                            shell_tools, tools_for)


def names(ts): return {t.__name__ for t in ts}
def by_name(ts): return {t.__name__: t for t in ts}


def outside_host(tmp_path):
    "A host whose reads may leave the open folders, and a sibling checkout holding the answer."
    root, sibling = tmp_path/'proj', tmp_path/'sibling'
    (root/'pkg').mkdir(parents=True)
    (root/'pkg'/'a.py').write_text('def a(): return 1\n')
    sibling.mkdir()
    (sibling/'notes.md').write_text('the answer is 42\n')
    return LocalHost([root], web=False, index=False, read_outside=True), root, sibling


# -- which tools a host earns ----------------------------------------------------------

def test_a_host_is_offered_exactly_the_groups_it_implements():
    """A capability the host does not have must not become a tool the model keeps failing to call,
    and the probe that decides must never do anything: `run_cmd` has no harmless call, so
    `_supports` asks whether the host overrode the method rather than running something. `drop`
    withholds groups the host *does* have, for a model that cannot afford their schemas.
    """
    bare = names(tools_for(NullHost(['/x'])))
    assert {'search_code', 'view_file'} <= bare
    assert not ({'run_python', 'notebook_cells', 'run_shell'} & bare)

    mem = names(tools_for(MemHost()))
    assert 'run_shell' in mem                  # MemHost overrides run_cmd
    assert 'run_python' not in mem             # list_vars/terminal_text absent, so the group drops

    h = MemHost()
    tools_for(h)
    assert h.cmds == [], 'the capability probe spawned something'

    full = names(tools_for(MemHost(), lambda: []))
    dropped = names(tools_for(MemHost(), lambda: [], drop=('shell', 'skill')))
    assert {'run_shell', 'read_skill'} <= full - dropped
    assert {'view_file', 'replace_text', 'search_code', 'grep'} <= dropped   # the core never drops


def test_a_narrow_host_says_why_rather_than_failing_silently():
    class H(NullHost):
        scopes = ('isolated',)
        def inspect_python(self, code, scope='isolated'):
            if scope not in self.scopes: return f'scope {scope!r} is not available here'
            return 'sandboxed ok'
    assert 'not available' in H(['/x']).inspect_python('x', 'overlay')


def test_a_lost_capability_ends_the_tool_call_not_the_turn():
    "A kernel dies mid-session. The model should read a failure, not have its turn raise."
    a, _ = fake_agent()
    def gone(): raise NotImplementedError('kernel is gone')
    gone.__name__ = 'list_vars'
    out = a._record(gone)()
    assert failed(out) and 'list_vars is not available here' in out


def test_every_tool_failure_is_spelled_the_same_way():
    "The activity feed and `Agent.problems` read this prefix; a tool that invents its own is invisible."
    fs = by_name(file_tools(MemHost()))
    assert failed(fs['view_file']('nope.py'))
    assert failed(fs['edit_file']('a.py', 'not json'))
    assert failed(fs['replace_text']('a.py', '[]'))
    assert tools.err('x') == ERR + 'x'
    assert failed(ERR + 'anything') and not failed('a normal result')


# -- editing and searching -------------------------------------------------------------

def test_file_edits_honor_an_optional_host_write_check():
    class Guarded(MemHost):
        def __init__(self):
            super().__init__({'/proj/a.py': 'x = 1\n'})
            self.checked = []
        def check_write(self, path):
            self.checked.append(str(path))
            return path
    h = Guarded(); tools = by_name(file_tools(h))
    assert not failed(tools['replace_text']('a.py', '[{"oldText": "x = 1", "newText": "x = 2"}]'))
    assert h.checked == ['/proj/a.py']
    h.checked.clear()
    assert failed(tools['edit_file']('a.py', 'not json'))
    assert h.checked == ['/proj/a.py']

def test_exact_text_editing_writes_only_when_every_edit_is_located():
    """All of it or none of it, so a rejected edit leaves the file exactly as it was: an ambiguous
    `oldText` and a stale one are both refusals, not partial writes. Three argument shapes are
    accepted because those are the three a model actually sends."""
    h = MemHost({'/proj/a.py': 'def a():\n    return 1\n'})
    rt = by_name(file_tools(h))['replace_text']
    assert not failed(rt('a.py', '[{"oldText": "return 1", "newText": "return 2"},'
                                 ' {"oldText": "def a():", "newText": "def b():"}]'))
    assert h.files['/proj/a.py'] == 'def b():\n    return 2\n'

    before = 'x = 1\nx = 1\n'
    h2 = MemHost({'/proj/a.py': before})
    rt2 = by_name(file_tools(h2))['replace_text']
    assert failed(rt2('a.py', '[{"oldText": "x = 1", "newText": "x = 2"}]'))   # ambiguous
    assert failed(rt2('a.py', '[{"oldText": "y = 9", "newText": "y = 8"}]'))   # stale
    assert h2.files['/proj/a.py'] == before

    for edits in ('[["a", "b"]]', [{'oldText': 'a', 'newText': 'b'}], {'oldText': 'a', 'newText': 'b'}):
        h3 = MemHost({'/proj/f.txt': 'a\n'})
        assert not failed(by_name(file_tools(h3))['replace_text']('f.txt', edits))
        assert h3.files['/proj/f.txt'] == 'b\n'


def test_grep_finds_every_literal_occurrence_and_refuses_what_it_cannot_compile():
    "What a rename or an audit needs: every place a string literally occurs, or an honest failure."
    h = MemHost({'/proj/a.py': 'import os\nos.getcwd()\n', '/proj/b.py': 'import sys\n'})
    g = by_name(code_tools(h))['grep']
    out = g('import')
    assert '/proj/a.py:1' in out and '/proj/b.py:1' in out
    assert '2 match(es) in 2 file(s)' in out
    assert 'no matches' in g('nothing_here')
    assert '/proj/a.py' in g('import', path_filter='a.py')
    assert '/proj/b.py' not in g('import', path_filter='a.py')

    bad = by_name(code_tools(MemHost()))['grep']
    assert failed(bad('(')) and failed(bad(''))
    lit = MemHost({'/proj/a.py': 'f(\n'})
    assert '/proj/a.py:1' in by_name(code_tools(lit))['grep']('(', regex=False)   # unless meant literally


# -- running a command -----------------------------------------------------------------

def test_a_command_is_run_once_and_its_failure_is_readable():
    "A non-zero exit is a result the model can act on, not an exception, and not a silent success."
    h = MemHost(commands={'pytest': (1, 'E   assert 1 == 2')})
    out = by_name(shell_tools(h))['run_shell']('pytest')
    assert failed(out) and 'exit 1' in out and 'command FAILED' in out and 'assert 1 == 2' in out
    assert h.cmds == [('pytest', None, 120)]

    ok = by_name(shell_tools(MemHost(commands={'true': (0, 'ok')})))['run_shell']('true')
    assert not failed(ok) and ok.startswith('exit 0')

    empty = MemHost()
    assert failed(by_name(shell_tools(empty))['run_shell']('  '))
    assert empty.cmds == [], 'an empty command was actually run'


def test_the_reference_host_runs_commands_interleaved_bounded_and_inside_the_folders(tmp_path):
    """A terminal or MCP agent that can edit but not run has no way to check its own work. The
    streams are interleaved so the model reads what a person would see, a hung command is killed
    rather than kept, and nothing starts outside the open folders."""
    h = LocalHost([str(tmp_path)], web=False, index=False)
    assert 'run_shell' in names(tools_for(h))
    assert h.run_cmd('') == (0, '')                          # the probe spawns nothing
    code, out = h.run_cmd('echo hello')
    assert code == 0 and 'hello' in out

    code, out = h.run_cmd('echo first; echo second 1>&2; exit 3')
    assert code == 3 and out.splitlines() == ['first', 'second']

    code, out = h.run_cmd('sleep 30', timeout=1)
    assert code == 124 and 'killed after 1s' in out

    inside = tmp_path/'inside'
    inside.mkdir()
    narrow = LocalHost([str(inside)], web=False, index=False)
    with pytest.raises(core.AgentError): narrow.run_cmd('pwd', cwd=str(tmp_path/'outside'))


# -- reading outside the open folders --------------------------------------------------

def test_reading_outside_the_folders_is_a_separate_decision_from_writing_outside(tmp_path):
    """The sandbox has two halves and only one was ever the point. Confining *writes* stops an
    agent damaging something nobody opened. Confining *reads* stops it answering a question whose
    answer is in a sibling checkout -- which is a cost as often as a protection, so it is a switch.

    Opening reads is a decision about source, not about the user's keys, and it never opens
    enumeration: a read outside is always a path the model already knew, never one it found by
    walking.
    """
    open_host, root, sibling = outside_host(tmp_path)
    shut = LocalHost([root], web=False, index=False)
    assert shut.read(sibling/'notes.md') is None
    assert open_host.read(sibling/'notes.md').strip() == 'the answer is 42'

    for call in (lambda: open_host.check(sibling/'notes.md'),
                 lambda: open_host.write(sibling/'notes.md', 'no')):
        with pytest.raises(core.AgentError, match='outside the open folders'): call()
    assert (sibling/'notes.md').read_text().strip() == 'the answer is 42'

    (sibling/'.env').write_text('OPENAI_API_KEY=sk-real\n')
    with pytest.raises(core.AgentError, match='credentials'):
        open_host.check(sibling/'.env', reading=True)
    assert open_host.read(sibling/'.env') is None
    assert tools.denied('/home/k/.ssh/id_rsa') and not tools.denied(root/'pkg'/'a.py')

    assert all(str(root) in str(p) for p in open_host.walk())
    ts = by_name(tools_for(open_host))
    assert 'sibling' not in ts['list_files']('notes.md')
    assert 'the answer is 42' in ts['view_file'](str(sibling/'notes.md'))
    assert failed(ts['create_file'](str(sibling/'new.py'), 'x = 1'))
    assert not (sibling/'new.py').exists()


def test_the_read_flag_is_a_host_capability_not_a_tool_assumption():
    "An older host that predates the flag must see its own call shape, not a new keyword."
    from pathlib import Path
    seen = []

    class OldHost(NullHost):
        def check(self, path, must_exist=False):
            seen.append((path, must_exist))
            return Path(path)

    assert not tools._takes_reading(OldHost)
    assert str(tools.readable(OldHost(['/proj']), '/anywhere/x.py')) == '/anywhere/x.py'
    assert seen == [('/anywhere/x.py', False)]


# -- reaching outward ------------------------------------------------------------------

def test_the_web_tools_ask_for_what_they_want_and_hand_back_only_the_digest(monkeypatch):
    """fossick's own default is ten results, so slicing twenty down to twenty quietly returned ten.
    And `research` returns a record; stringifying the whole `{query, sources, digest, dropped}` sent
    the same markdown twice, once in dict syntax."""
    import fossick
    asked = {}

    def search(q, **kw):
        asked.update(q=q, **kw)
        return [{'title': f'r{i}', 'href': f'https://x/{i}'} for i in range(kw.get('n', 10))]

    monkeypatch.setattr(fossick, 'search', search)
    host = LocalHost(['.'], web=True, index=False)
    assert len(host.web_search('nbdev export', n=20)) == 20 and asked['n'] == 20

    monkeypatch.setattr(fossick, 'research', lambda q, **kw: {
        'query': q, 'sources': [{'title': 't', 'href': 'https://x', 'md': 'body'}],
        'digest': '## t\nhttps://x\n\nbody', 'dropped': []})
    out = LocalHost(['.'], web=True, index=False).research('what is nbdev')
    assert out == '## t\nhttps://x\n\nbody' and 'dropped' not in out


def test_the_code_index_uses_its_graph_setting_for_sync_and_search(monkeypatch, tmp_path):
    """A graph is built and queried together, or neither operation uses one."""
    import kosha
    seen = []

    class FakeKosha:
        # `**kw`, not `dir=None`: `sync_index` also passes `busy_timeout`, and a fake that
        # rejects it raises inside the sync thread, where the error is swallowed and this
        # test silently stops reaching `sync` at all
        def __init__(self, **kw): pass
        def sync(self, **kw):
            seen.append(('sync', kw['graph']))
            return self
        def context(self, **kw):
            seen.append(('context', kw['graph']))
            return []

    monkeypatch.setattr(kosha, 'Kosha', FakeKosha)
    for graph in False, True:
        host = LocalHost([tmp_path], web=False, graph=graph)
        host.wait_index()
        host._semantic('query', 1)
    assert seen == [('sync', False), ('context', False), ('sync', True), ('context', True)]


def test_search_fuses_legs_with_litesearch_rrf_and_rgapi(tmp_path, monkeypatch):
    """LocalHost.search must use litesearch.rrf_all (same as Vault.federate) and rgapi, not a
    hand-rolled subprocess rg / fossick URL adapter."""
    import ramabana.tools as T
    root = tmp_path
    (root/'a.py').write_text('def alpha(): pass\n')
    (root/'b.py').write_text('def beta(): pass\n')
    host = T.LocalHost([root], web=False, index=False)
    # literal leg
    hits = host._rg('def', limit=10)
    assert hits and all(hasattr(h, 'path') and hasattr(h, 'line') for h in hits)
    # fusion identity
    left = [T.Hit(str(root/'a.py'), 1, '', 'alpha')]
    right = [T.Hit(str(root/'a.py'), 1, '', 'alpha'), T.Hit(str(root/'b.py'), 1, '', 'beta')]
    fused = T._fuse([left, right], 10)
    assert fused[0].path.endswith('a.py')  # appears in both legs -> ranks first
    # walk via rgapi.fd (or fallback) skips nothing essential
    walked = {p.name for p in host.walk()}
    assert walked == {'a.py', 'b.py'}


def test_a_root_can_be_opened_after_the_host_is_built(tmp_path):
    """Roots were fixed at construction, so reaching a folder outside them meant quitting the
    session and starting again with a different `--root`. The write boundary can widen; what it
    cannot do is widen quietly, so the host remembers which ones were added.
    """
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir(); b.mkdir(); (b/'f.txt').write_text('hi')
    h = LocalHost(roots=[str(a)], index=False)

    with pytest.raises(AgentError): h.check(b/'f.txt')     # outside, so refused
    assert h.add_root(str(b)) == str(b.resolve())
    assert str(b.resolve()) in h.roots
    h.check(b/'f.txt')                                     # and now it is not
    assert h.added_roots == [str(b.resolve())]             # remembered, for what /resume must say

    assert h.add_root(str(b)) == str(b.resolve())          # adding it twice is not an error
    assert h.roots.count(str(b.resolve())) == 1
    with pytest.raises(AgentError): h.add_root(str(tmp_path/'nope'))
    with pytest.raises(AgentError): h.add_root(str(b/'f.txt'))   # a file is not a root


def test_the_agent_asks_before_it_widens_its_own_boundary(tmp_path):
    "`add_root` is a write: the agent may propose one, and a person decides. `--approve off` refuses."
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir(); b.mkdir()
    assert 'add_root' in tools.WRITE_TOOLS, 'it must go through the same gate as a write'

    h = LocalHost(roots=[str(a)], index=False)
    fn = {t.__name__: t for t in tools.tools_for(h)}.get('add_root')
    assert fn is not None, 'the tool is not offered'
    assert str(b.resolve()) in fn(str(b))
    assert str(b.resolve()) in h.roots

    assert ERR in fn(str(tmp_path/'nope'))          # a refusal reads as a tool error, not a crash
