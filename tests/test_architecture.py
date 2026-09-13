"""The package boundary: Shalya describes tools; Ramabana composes them into an agent."""

from ramabana.agent import Approvals
from ramabana.cli import WorkspaceHost, mk_agent, mk_host
from ramabana.mcp import _annotate
from ramabana.racp import EditorHost
from ramabana.shop import Cart, cart_tools
from ramabana.testing import MemHost, fake_agent
from ramabana.tools import ToolCatalog, tools_for


def test_one_catalog_drives_policy_summary_and_mcp_metadata():
    catalog = ToolCatalog([*tools_for(MemHost()), *cart_tools(Cart())])
    edit, search = catalog['edit_file'], catalog['search_code']

    assert edit.group == 'file' and edit.writes and edit.available
    assert search.group == 'code' and not search.writes and search.available
    assert catalog.summarise('search_code', {'query': 'catalog'}) == 'Search catalog'
    assert 'cart_add' not in catalog.read_only().names
    assert _annotate(edit).destructiveHint is True
    assert _annotate(search).readOnlyHint is True


def test_agent_keeps_catalogs_instead_of_parallel_tool_caches():
    approvals = Approvals(mode='auto')
    agent, _ = fake_agent(approvals=approvals)
    names = {tool.__name__ for tool in agent.tools}

    assert names == set(agent.catalog.names)
    assert approvals.tools == agent.catalog.writes
    assert not hasattr(agent, '_subtools')
    assert not hasattr(agent, '_subrec')
    assert {tool.__name__ for tool in agent._sub_plain()} == names


def test_every_frontend_uses_one_provider_capable_host(tmp_path):
    plain = mk_host([tmp_path], web=False, index=False)
    both = mk_host([tmp_path], web=False, vault=True, spec=True,
                   warm=False, index=False)

    assert type(plain) is WorkspaceHost
    assert type(both) is WorkspaceHost
    assert {'memory', 'api'} <= both.provides
    assert not ({'memory', 'api'} & plain.provides)
    assert issubclass(EditorHost, WorkspaceHost)
