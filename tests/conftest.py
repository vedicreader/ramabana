"Pytest fixtures for the plain-python suite; one file per feature block, and nothing loads a model."

import pytest
from ramabana.testing import SPEC

@pytest.fixture(scope='session', autouse=True)
def _prime_tool_summaries():
    "Build every tool group once so `summarise` has its labels, whatever the worker or test order."
    from ramabana.testing import FullHost
    from ramabana.tools import tools_for
    from shalya.tools import watch_tools, memory_tools
    h = FullHost(); tools_for(h); watch_tools(h); memory_tools(h)

@pytest.fixture
def spec(): return SPEC


@pytest.fixture
def hide_runtime(monkeypatch):
    "Make one rishi runtime look uninstalled for the length of a test."
    import ramabana.core as core
    real = core.runtime_available
    return lambda runtime: monkeypatch.setattr(core, 'runtime_available', lambda rt: rt != runtime and real(rt))
