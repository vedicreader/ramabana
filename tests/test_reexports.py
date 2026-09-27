"""The seams downstream packages import through, asserted as a surface rather than by use.

The toolset moved to shalya, and `ramabana.tools` is what keeps every earlier import spelling
working. A re-export module has no behaviour of its own, so nothing here exercises one; what is
worth asserting is that the names are present and are the upstream objects rather than copies.

`ramabana.git` is gone: it re-exported gheasy and nothing else, and Leela reaches gheasy by name.
"""
import importlib

import pytest

import ramabana.core, ramabana.tools

#: Leela's import surface, by module.
LEELA_ELSEWHERE = {'ramabana.core': ['AgentError', 'agent_err', 'env'],
                   'ramabana.tools': ['WRITE_TOOLS', 'failed', 'read_only'],
                   'ramabana.vault': ['safe_shelf'],
                   'ramabana.cli': ['MEDIA', 'Attachment', 'media_note', 'media_parts']}


@pytest.mark.parametrize('mod,names', sorted(LEELA_ELSEWHERE.items()))
def test_every_other_name_leela_imports_is_still_reachable(mod, names):
    m = pytest.importorskip(mod)
    assert [n for n in names if not hasattr(m, n)] == []


def test_the_tool_re_exports_are_the_upstream_objects_and_not_copies():
    """A copy would drift on the next shalya release without a test failing anywhere.

    Only `failed` is a bare re-export. `WRITE_TOOLS` gains ramabana's own writing tools and
    `read_only` is wrapped, so identity is asserted where the name really is one and the
    relationship where it is not.
    """
    sc = importlib.import_module('shalya.core')
    assert ramabana.tools.failed is sc.failed
    assert ramabana.tools.WRITE_TOOLS > sc.WRITE_TOOLS, 'extended, not replaced'


def test_every_name_the_re_export_module_promises_actually_resolves():
    "`__all__` is generated from `_all_`, so a name listed and not imported fails only on use."
    assert [n for n in ramabana.tools.__all__ if not hasattr(ramabana.tools, n)] == []


def test_every_name_the_seam_claims_to_re_export_is_really_shalyas():
    "A local binding satisfies `hasattr(ramabana.tools, n)`, so the seam is asserted against `shalya` itself."
    import shalya
    assert [n for n in ramabana.tools._all_ if not hasattr(shalya, n)] == []


def test_the_phase_3_names_reach_through_the_shim():
    "shalya 0.1.0's opt-in factories and `attempt` are part of the seam, so leela can spell them as before."
    import ramabana.tools as t, shalya.tools as st, shalya.core as sc
    assert t.OPTIN is st.OPTIN and t.attempt is sc.attempt and t.legacy_tools is st.legacy_tools
    assert t.exhash_tools is st.exhash_tools and t.research_tools is st.research_tools and t.author_tools is st.author_tools


def test_agent_error_is_the_host_refusal_shalya_raises():
    "`except AgentError` is the spelling the harness and Leela both use for what a host refuses."
    from shalya.core import HostError
    assert ramabana.core.AgentError is HostError
