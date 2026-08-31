"""The seams downstream packages import through, asserted as a surface rather than by use.

The toolset moved to shalya and the git plumbing to gheasy, and `ramabana.tools` and `ramabana.git`
are what keeps every earlier import spelling working. A re-export module has no behaviour of its
own, so nothing here exercises one; what is worth asserting is that the names are present and are
the upstream objects rather than copies.

`from gheasy.repo import *` skips the underscored names and gheasy carries no tool sets, so both
have to be listed by hand. That hand-written list is the thing that goes stale, which is why the
names Leela imports are written out here in full instead of being derived from `__all__`.
"""
import importlib

import pytest

import ramabana.core, ramabana.git, ramabana.tools

#: Every name Leela imports from `ramabana.git`, from `leela/blocks/`, `leela/core/` and its tests.
LEELA_GIT = ['GIT_READ_TOOLS', 'GIT_TOOLS', 'GIT_WRITE_TOOLS', 'GitError', 'GitGateway', 'GitRepo',
             '_conflict_blocks', '_invalidate', '_plural', '_run', '_unborn', 'classify', 'clone',
             'clone_target', 'gateway', 'git_tools', 'repo_root', 'url_name']

#: The rest of Leela's import surface, by module.
LEELA_ELSEWHERE = {'ramabana.core': ['AgentError', 'agent_err', 'env'],
                   'ramabana.tools': ['WRITE_TOOLS', 'failed', 'read_only'],
                   'ramabana.vault': ['safe_shelf'],
                   'ramabana.cli': ['MEDIA', 'Attachment', 'media_note', 'media_parts']}


@pytest.mark.parametrize('name', LEELA_GIT)
def test_every_git_name_leela_imports_is_still_reachable(name):
    """`_run` and `_conflict_blocks` went missing when the plumbing moved to gheasy, and the three
    tool sets went with the toolset to shalya. Leela reaches `_run` from `_stage`, which runs only
    on a conflicted file, so the break did not show at import time in either repository."""
    assert hasattr(ramabana.git, name), f'ramabana.git lost {name}'


@pytest.mark.parametrize('mod,names', sorted(LEELA_ELSEWHERE.items()))
def test_every_other_name_leela_imports_is_still_reachable(mod, names):
    m = pytest.importorskip(mod)
    assert [n for n in names if not hasattr(m, n)] == []


def test_the_git_re_exports_are_the_upstream_objects_and_not_copies():
    "A copy would drift on the next gheasy or shalya release without a test failing anywhere."
    gr, sc = importlib.import_module('gheasy.repo'), importlib.import_module('shalya.core')
    assert ramabana.git._run is gr._run
    assert ramabana.git._conflict_blocks is gr._conflict_blocks
    assert ramabana.git.GitRepo is gr.GitRepo
    for n in ('GIT_TOOLS', 'GIT_READ_TOOLS', 'GIT_WRITE_TOOLS'):
        assert getattr(ramabana.git, n) is getattr(sc, n), n


def test_every_name_the_re_export_modules_promise_actually_resolves():
    "`__all__` is generated from `_all_`, so a name listed and not imported fails only on use."
    for m in (ramabana.git, ramabana.tools):
        assert [n for n in m.__all__ if not hasattr(m, n)] == [], m.__name__


def test_agent_error_is_the_host_refusal_shalya_raises():
    "`except AgentError` is the spelling the harness and Leela both use for what a host refuses."
    from shalya.core import HostError
    assert ramabana.core.AgentError is HostError
