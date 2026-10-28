"Pytest fixtures for the plain-python suite, with model downloads confined to the controller."

import os, sys, tempfile, time, pytest
from importlib.util import find_spec
from pathlib import Path
# a scratch home before ramabana is imported: the suite read the real ~/.config, skills and vault, and failed as they grew.
# macOS finds the login keychain under $HOME/Library/Keychains; without it a tool that saves a login raised a 'keychain not found' dialog
_real, _home = Path.home(), Path(tempfile.mkdtemp(prefix='ramabana-home-'))
if (_real/'Library'/'Keychains').is_dir():
    (_home/'Library').mkdir(); (_home/'Library'/'Keychains').symlink_to(_real/'Library'/'Keychains')
# Model and vocabulary caches must survive each process's scratch HOME.
os.environ.setdefault('HF_HOME', str(_real/'.cache'/'huggingface'))
os.environ.setdefault('LAGHU_CACHE', str(Path(os.environ.get('XDG_CACHE_HOME') or _real/'.cache')/'laghu'))
os.environ.setdefault('LITESEARCH_CACHE', str(_home/'.cache'/'litesearch'))
# usearch otherwise downloads its SQLite extension into every scratch HOME.
os.environ['VIRTUAL_ENV'] = sys.prefix
os.environ['HOME'] = str(_home); os.environ.pop('RAMABANA_CONFIG', None)
os.environ.pop('SANKETA_KEYMAPS', None)   # a session start writes its keymap there; the scratch HOME has no Sanketa folder
from ramabana.testing import SPEC


def pytest_configure(config):
    "Populate shared download caches before xdist starts its workers."
    if hasattr(config, 'workerinput') or find_spec('vishalakshi') is None: return
    from litesearch import static_embedder, static_code_embedder
    from litesearch.postfix import usearch_lib
    from vishalakshi.core import DFLT_ENC
    started = time.perf_counter()
    static_embedder(DFLT_ENC)
    static_code_embedder()
    usearch_lib()
    os.environ['HF_HUB_OFFLINE'] = '1'
    print(f'Preloaded vault and code encoders in {time.perf_counter() - started:.3f}s; workers use HF_HUB_OFFLINE=1')


@pytest.fixture(scope='session', autouse=True)
def _vault_encoders():
    "Prime litesearch's per-process encoder cache before hosts can open vaults on threads."
    if find_spec('vishalakshi') is None: return
    from litesearch import static_embedder, static_code_embedder
    from vishalakshi.core import DFLT_ENC
    static_embedder(DFLT_ENC)
    static_code_embedder()

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
