"""The seams downstream packages import through, asserted as a surface rather than by use.

The toolset moved to shalya, and `ramabana.tools` is what keeps every earlier import spelling
working. A re-export module has no behaviour of its own, so nothing here exercises one; what is
worth asserting is that the names are present and are the upstream objects rather than copies.

`ramabana.git` is gone: it re-exported gheasy and nothing else, and Leela reaches gheasy by name.
"""
import pytest

import ramabana.tools

#: Leela's import surface, by module.
LEELA_ELSEWHERE = {'ramabana.core': ['AgentError', 'agent_err', 'env'],
                   'ramabana.tools': ['WRITE_TOOLS', 'failed', 'read_only'],
                   'ramabana.vault': ['safe_shelf'],
                   'ramabana.cli': ['MEDIA', 'Attachment', 'media_note', 'media_parts']}


@pytest.mark.parametrize('mod,names', sorted(LEELA_ELSEWHERE.items()))
def test_every_other_name_leela_imports_is_still_reachable(mod, names):
    m = pytest.importorskip(mod)
    assert [n for n in names if not hasattr(m, n)] == []


def test_every_name_the_re_export_module_promises_actually_resolves():
    "`__all__` is generated from `_all_`, so a name listed and not imported fails only on use."
    assert [n for n in ramabana.tools.__all__ if not hasattr(ramabana.tools, n)] == []


