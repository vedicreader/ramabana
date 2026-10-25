"Pytest fixtures for the plain-python suite; one file per feature block, and nothing loads a model."

import os, tempfile, pytest
# a scratch home before ramabana is imported: the suite read the real ~/.config, skills and vault, and failed as they grew
os.environ['HOME'] = tempfile.mkdtemp(prefix='ramabana-home-'); os.environ.pop('RAMABANA_CONFIG', None)
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


@pytest.fixture(autouse=True)
def _own_config(tmp_path_factory, monkeypatch):
    "Point every test at a config.toml of its own, so none reads or writes the machine's."
    monkeypatch.setenv('RAMABANA_CONFIG', str(tmp_path_factory.mktemp('config')/'config.toml'))


@pytest.fixture(autouse=True)
def _own_aliases(tmp_path_factory, monkeypatch):
    "Saved aliases in a file of each test's own, and no Azure OpenAI from the machine's environment."
    import ramabana.core as core
    monkeypatch.setattr(core, 'MODEL_ALIASES', tmp_path_factory.mktemp('aliases')/'models.json')
    for k in ('AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_DEPLOYMENTS'): monkeypatch.delenv(k, raising=False)
