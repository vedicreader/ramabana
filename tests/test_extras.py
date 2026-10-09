"Each extra is optional: with its packages blocked from import, the core still runs and the missing features name the extra."
import re, subprocess, sys, textwrap, tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

from ramabana.core import EXTRAS

PYPROJECT = Path(__file__).parent.parent/'pyproject.toml'

#: a child Python in which the top-level names in `sys.argv[1]` do not import, as if never installed
BLOCK = '''
import importlib.abc, sys
BLOCKED = set(sys.argv[1].split(','))
class Blocked(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.partition('.')[0] in BLOCKED: raise ImportError(f'{name} is blocked', name=name)
sys.meta_path.insert(0, Blocked())
import io, contextlib, tempfile
d = tempfile.mkdtemp()
def said(f, *a, **kw):
    "`(f's return, what it printed to stderr)`."
    with contextlib.redirect_stderr(io.StringIO()) as e: r = f(*a, **kw)
    return r, e.getvalue()
def core_runs():
    "`import ramabana`, an `Agent` with its tools and system prompt, on a plain host; the tool names."
    import ramabana
    from shalya.host import LocalHost
    from ramabana.testing import fake_agent
    a, _ = fake_agent(LocalHost([d], index=False))
    assert a.system_prompt() and a.tools
    names = {t.__name__ for t in a.tools}
    assert {'view_file', 'replace_text', 'grep', 'run_shell'} <= names, names
    return names
'''

def run(blocked, code):
    "Run `code` after `BLOCK` in a fresh interpreter; fail with its stderr unless it exits 0."
    r = subprocess.run([sys.executable, '-c', BLOCK + textwrap.dedent(code), ','.join(blocked)],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-3000:]
    return r.stdout

def _norm(name): return re.sub(r'[-_.]+', '-', name).lower()
def _name(req): return _norm(re.split(r'[\s\[<>=!~;]', req.strip(), maxsplit=1)[0])
def _selves(reqs): return {x.strip() for r in reqs if _name(r) == 'ramabana' for x in r[r.index('[')+1:r.index(']')].split(',')}

def test_pyproject_declares_a_lean_core_and_nested_extras():
    d = tomllib.loads(PYPROJECT.read_text())
    core, ex = {_name(r) for r in d['project']['dependencies']}, d['project']['optional-dependencies']
    assert set(ex) == {'search', 'python', 'serve', 'cli', 'dhrona', 'all'}
    assert {'search', 'python'} <= _selves(ex['cli'])
    assert _selves(ex['all']) == set(ex) - {'all'}
    assert 'ramabana[all]' in d['dependency-groups']['dev']
    own = {k: {_name(r) for r in v} - {'ramabana', 'shalya'} for k, v in ex.items()}
    assert not core & set().union(*own.values()), 'a package is both core and optional'
    dists = packages_distributions()
    for extra, mods in EXTRAS.items():
        for m in mods: assert {_norm(n) for n in dists.get(m, ())} & own[extra], f'{m} is not installed by ramabana[{extra}]'

def test_without_search_the_agent_runs_and_search_memory_and_web_say_what_to_install():
    run(EXTRAS['search'], '''
    from ramabana.core import AgentError, need
    from ramabana.vault import WorkspaceHost
    from ramabana.spec import SpecError, load_spec
    from ramabana.cli import main
    names = core_runs()
    assert not names & {'search_code', 'web_search', 'read_url'}, names
    assert "pip install 'ramabana[search]'" in need('search')
    try: WorkspaceHost([d], vault=True, index=False); raise AssertionError('opened a vault without vishalakshi')
    except AgentError as e: assert 'ramabana[search]' in str(e)
    try: load_spec('https://example.com/spec.json'); raise AssertionError('fetched without fossick')
    except SpecError as e: assert 'ramabana[search]' in str(e)
    rc, err = said(main, prompt='hi', root=d, vault=True, approve='auto', tmux='off')
    assert rc == 2 and 'ramabana[search]' in err, (rc, err)
    ''')


def test_the_bare_core_runs_with_every_extra_blocked():
    run({m for ms in EXTRAS.values() for m in ms} | {'rich', 'fastmux'}, '''
    import ramabana.agent, ramabana.monitor, ramabana.runtime, ramabana.spec, ramabana.tools, ramabana.vault
    names = core_runs()
    assert not names & {'search_code', 'web_search', 'read_url'}, names
    ''')


