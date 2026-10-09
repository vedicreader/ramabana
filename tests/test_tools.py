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
from ramabana.tools import LocalHost, failed, file_tools, tools_for


def by_name(ts): return {t.__name__: t for t in ts}


def outside_host(tmp_path):
    "A host whose reads may leave the open folders, and a sibling checkout holding the answer."
    root, sibling = tmp_path/'proj', tmp_path/'sibling'
    (root/'pkg').mkdir(parents=True)
    (root/'pkg'/'a.py').write_text('def a(): return 1\n')
    sibling.mkdir()
    (sibling/'notes.md').write_text('the answer is 42\n')
    return LocalHost([root], web=False, index=False, read_outside=True), root, sibling


# -- editing and searching -------------------------------------------------------------


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
    assert 'sibling' not in ts['ls'](pattern='notes.md', recursive=True)
    assert 'the answer is 42' in ts['view_file'](str(sibling/'notes.md'))
    assert failed(ts['create_file'](str(sibling/'new.py'), 'x = 1'))
    assert not (sibling/'new.py').exists()


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


def test_a_sub_agent_sized_like_its_parent_is_not_handed_an_empty_list():
    """When the sub-agent budget matches the turn's there is no separate list to build, so the
    answer is the parent's own. That list is written while `tools` is built, and asking for it
    before anything asked for `tools` used to hand delegation nothing at all."""
    a, _ = fake_agent()
    assert a.subagent_budget == a.budget, 'one model, one budget: this is the shared-list branch'
    assert a._sub_plain(), 'read cold, before `tools` was ever touched'
    warm = {t.__name__ for t in a._sub_plain()}
    a.tools
    assert {t.__name__ for t in a._sub_plain()} == warm, 'and it does not change once warm'


# ---- entering python mode keeps every group the host already had -------------------------

class _Kernel:
    "The shape `LocalHost` expects of a kernel. `/python` attaches one of these."
    scopes, kind = ('isolated', 'overlay'), 'ipykernel'
    def run(self, code): return 'ran'
    def inspect(self, code, scope='isolated'): return 'inspected'
    def list_vars(self): return ''


def test_entering_python_mode_keeps_every_tool_the_host_already_had(tmp_path):
    """`/python` used to build a replacement host from four attributes of the old one.

    A session started with `--vault --spec` lost fifteen tools and gained none, because every
    group the old host had and `LocalHost` does not went with the host it replaced. A kernel is
    a backend on the host now, so there is nothing to copy and nothing to drop.
    """
    from ramabana.cli import mk_host
    host = mk_host(roots=(str(tmp_path),), vault=True, spec=True)
    before = {t.__name__ for t in tools_for(host)}
    assert {'memory_read', 'api_load', 'list_watches'} <= before, sorted(before)
    host.kernel = _Kernel()                       # what `use_kernel` does
    after = {t.__name__ for t in tools_for(host)}
    assert before == after, f'lost {sorted(before - after)}, gained {sorted(after - before)}'


