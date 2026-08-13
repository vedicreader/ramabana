"""Pytest fixtures for the plain-python suite.

One file per feature block (routing, context, tools, turn, vault, …).
Notebooks carry the readable `test_eq` examples; these tests assert contracts in bulk.
Nothing here loads a model.
"""

import pytest

from ramabana.testing import SPEC


@pytest.fixture
def spec(): return SPEC


@pytest.fixture
def hide_runtime(monkeypatch):
    "Make one rishi runtime look uninstalled for the length of a test."
    import ramabana.core as core
    real = core.runtime_available
    return lambda runtime: monkeypatch.setattr(
        core, 'runtime_available', lambda rt: rt != runtime and real(rt))
