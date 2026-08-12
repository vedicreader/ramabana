"""Fixtures for the harness suite."""

import pytest

from ramabana.testing import SPEC


@pytest.fixture
def spec(): return SPEC


@pytest.fixture
def hide_runtime(monkeypatch):
    """Make one of Rishi's optional runtimes look uninstalled, for the length of one test.

    Whether MLX or LiteRT can be imported is a property of the machine, not of the harness. Tests
    that borrowed the absence from the venv passed until `rishi[all]` brought the runtime in, and
    then failed with nothing wrong in the code, so a test about a missing runtime says so here.
    """
    import ramabana.core as core
    def _hide(runtime):
        dep, real = core._RUNTIME_DEPS[runtime], core.importlib.util.find_spec
        monkeypatch.setattr(core.importlib.util, 'find_spec',
                            lambda name: None if name == dep else real(name))
    return _hide
