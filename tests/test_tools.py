"""The tools themselves: which ones a host earns, what they return, and where they may reach.

One functional block, gathered from `test_shell_and_context.py` and the sandbox half of
`test_harness.py`. The briefing that describes these tools is a different block and lives in
`test_briefing.py`; what is here is the tools' own behaviour.

Most of this surface came back from leela when ramabana became the shared agent core, and none of
it had a test in either repository before the move.
"""
from ramabana.testing import MemHost, fake_agent
from ramabana.tools import LocalHost, NullHost, failed, file_tools, tools_for


def names(ts): return {t.__name__ for t in ts}


# -- which tools a host earns ----------------------------------------------------------

def test_a_host_is_offered_exactly_the_groups_it_declares():
    """A capability the host does not have must not become a tool the model keeps failing to call.

    One rule decides: the host declares a group by inheriting the class that names it, and
    `provides` reads the declarations. `drop` withholds groups the host *does* have, for a model
    that cannot afford their schemas.
    """
    bare = names(tools_for(NullHost(['/x'])))
    assert 'view_file' in bare                 # every host has the path boundary the file tools need
    assert not ({'search_code', 'run_python', 'notebook_cells', 'run_shell'} & bare)

    mem = names(tools_for(MemHost()))
    assert {'search_code', 'run_shell'} <= mem          # MemHost declares code and shell
    assert not ({'run_python', 'notebook_cells', 'memory_tree', 'api_load'} & mem)

    h = MemHost()
    tools_for(h)
    assert h.cmds == [], 'the capability probe spawned something'

    full = names(tools_for(MemHost(), lambda: []))
    dropped = names(tools_for(MemHost(), lambda: [], drop=('shell', 'skill')))
    assert {'run_shell', 'read_skill'} <= full - dropped
    assert {'view_file', 'replace_text', 'search_code', 'grep'} <= dropped   # the core never drops


def test_a_lost_capability_ends_the_tool_call_not_the_turn():
    "A kernel dies mid-session. The model should read a failure, not have its turn raise."
    a, _ = fake_agent()
    def gone(): raise NotImplementedError('kernel is gone')
    gone.__name__ = 'list_vars'
    out = a._record(gone)()
    assert failed(out) and 'list_vars is not available here' in out


# -- editing and searching -------------------------------------------------------------


# -- running a command -----------------------------------------------------------------


# -- reading outside the open folders --------------------------------------------------


# -- reaching outward ------------------------------------------------------------------

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
    assert {'memory_tree', 'api_load', 'list_watches'} <= before, sorted(before)
    host.kernel = _Kernel()                       # what `use_kernel` does
    after = {t.__name__ for t in tools_for(host)}
    assert before == after, f'lost {sorted(before - after)}, gained {sorted(after - before)}'

def test_a_host_that_cannot_write_is_offered_no_editors():
    """`NullHost.write` raises, so advertising `create_file`, `edit_file` and `replace_text`
    hands a model three tools that can only fail. It gets `view_file` and nothing else, without
    needing `readonly=True` to make it honest."""
    assert names(file_tools(NullHost(['/x']))) == {'view_file'}
    assert names(tools_for(NullHost(['/x']))) == {'view_file'}
    assert NullHost().writes is False

    assert MemHost().writes is True                      # it writes into its dict, so it keeps them
    assert {'create_file', 'edit_file', 'replace_text'} <= names(file_tools(MemHost()))

    class Frozen(MemHost): writes = False
    assert names(file_tools(Frozen())) == {'view_file'}   # the flag decides, not the class
