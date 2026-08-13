"""The hands: what the application under the agent must provide, and every tool built on top of it.

## The host

`Host` is the application under an agent, as an interface. Every method may raise, and
the tools catch rather than let an exception end a turn. A capability that cannot be
supported raises `NotImplementedError`, which `tools_for` reads as "do not offer this tool"
-- an agent told about a tool that always fails is worse off than one never told about it.

`NullHost` is a host with nothing behind it, and it is the reference implementation of
"absent" -- the harness runs bare on it, which is how the probing in `tools_for` gets
tested without a real application.

## A host over real folders

`LocalHost` is the reference implementation: enough of a host to run the agent from a
terminal, from an MCP server or from a test, with no IDE anywhere. It is also where the
sandbox actually lives -- `check` resolves `..` and symlinks *before* comparing against the
open folders, so every other method may assume its argument was approved.

## Skills

A skill is know-how the agent can read on demand: a package that documents itself, or a
`SKILL.md` file in a repository. Only names and one-line descriptions go in the system
prompt; the bodies are fetched by the `read_skill` tool, which is what keeps a dozen skills
affordable.

Skills come from installed packages (the `pyskills` entry-point group) and from
`<name>/SKILL.md` directories. The precedence is deliberate: a file beats a package,
because the package's skill is the general advice and the one in your own repository is
the correction.

`skill_index` is what goes in the system prompt, and `find` is how `read_skill` resolves
what the model asked for.

## Extensions

An extension is a Python file the user drops in a directory. `Registry` is everything it
is handed: tools, skills, slash commands, lifecycle hooks and the approval policy. What is
deliberately absent is any route to a backend's internals -- an extension that pokes at a
litert conversation would break on the next model switch, and break silently.

## Tool plumbing

Three things every tool shares: a clip, because the context window is the scarce resource;
a parser for the hash-verified edit commands models emit as JSON; and a probe that asks a
host whether a capability exists. `WRITE_TOOLS` names the tools that change something,
which is the line an approval policy draws.

## Seeing the code

The first group any host gets: search the index, find code shaped like a given function,
outline a file, list the files. Every result names the exact path and how to address it,
because a model that has to guess whether something is a notebook will guess wrong.

## Files

Files are read and written by hash-verified address. `view_file` returns
`lineno|hash|content` lines, and those hashes are the addresses `edit_file` takes -- so the
view is also the address book, and an edit built on a stale view fails instead of damaging
the wrong line.

## Notebooks

The harness deliberately does not own a notebook representation: exhash addresses cells by
path and id without one, so only the two operations that genuinely need to know what a
notebook *is* are delegated to the host.

## The web and remembered research

Two groups, and the split matters: the web tools go out now, while the memory tools recall
pages read earlier as whole document sections. A question that was researched last week
should cost a memory search rather than another crawl.

## The live session

The user's kernel, and the terminal they are looking at. `run_python` lands in their
namespace and is a write tool; `inspect_python` cannot change anything and is not, which is
why the briefing tells the model to reach for it first. `read_terminal` is read-only by
construction: it shows what the user ran and cannot run anything.

`ask_memory` is the odd one in that group: a model call inside a tool call, which the harness
otherwise avoids. It earns it the same way `delegate` does -- the alternative is every section
of every candidate document arriving in the caller's context so it can read them itself -- and
it is also the only way to answer out of material the caller must not see. A host whose store
holds private documents answers those on a model that is not the caller, and hands back what
that model was willing to say. It appears only for a host that implements `Host.ask`.

`memory_tools` recalls what was read. `watch_tools` is the other direction: what the agent
arranged to read later. The two share a store deliberately -- a reminder that fires becomes an
ordinary note, so "what am I supposed to be doing" and "what do I know" are one query, and
neither needs a notification channel the harness does not have.

## Skills as tools

`read_skill` is what makes the index in the system prompt affordable: names and
descriptions go out with every turn, bodies only when asked for. `create_skill` writes a
project-local `SKILL.md`, and never overwrites one.

## Assembling the tool list

`tools_for` probes each group with a harmless call and drops the whole group when the host
does not implement it. Whole groups rather than individual tools, because the groups are the
real units of capability: a host with no notebook representation cannot support any of the
four notebook tools.

## Sub-agents

Delegation is a context strategy, not a speed one. A broad question that takes twenty tool
calls to answer costs the caller one question and one answer, because the sub-agent's
working is discarded with its conversation. A sub-agent gets read-only tools, and cannot
delegate further: recursion here is a fan-out tree whose width nobody chose.

`delegate` runs one question in a throwaway conversation on the same engine, and closes it
in a `finally` -- a sub-agent whose context leaks back into the session is just a slower way
of doing the work inline.

The tools themselves take callables rather than a backend, so a model switch mid-session is
picked up -- the tool the model is holding must not be pinned to whichever backend happened
to be current when the list was built.

Docs: https://vedicreader.github.io/ramabana/tools.html.md"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/02_tools.ipynb.

# %% auto #0
__all__ = ['MAX_GREP_HITS', 'SANDBOX', 'SECRET', 'NO_ROOTS', 'DENY', 'SKIP_DIRS', 'SKIP_SUFFIXES', 'MAX_FILE', 'MAX_VARS',
           'LD_CHARS', 'GROUP', 'EXTRA_MODULES', 'MAX_SKILL_CHARS', 'SKILL_DESC_MAX', 'EVENTS', 'MAX_TOOL_CHARS',
           'MAX_HITS', 'WRITE_TOOLS', 'ERR', 'SUB_MAX_STEPS', 'SUB_SP', 'NO_SUB', 'Hit', 'Host', 'NullHost', 'denied',
           'ld_json', 'LocalHost', 'Skill', 'skill_dirs', 'discover', 'skill_index', 'find', 'Registry', 'ext_dirs',
           'load', 'err', 'failed', 'clip', 'clip_lines', 'readable', 'code_tools', 'file_tools', 'notebook_tools',
           'web_tools', 'memory_tools', 'api_tools', 'watch_tools', 'session_tools', 'shell_tools', 'skill_tools',
           'tools_for', 'read_only', 'sub_sp', 'delegate', 'delegate_many', 'named_skills', 'subagent_tools']

# %% ../nbs/02_tools.ipynb #48255398
import ast, functools, json, os, re, runpy, shutil, threading, uuid
from dataclasses import dataclass, field
from pathlib import Path
from fastcore.basics import AttrDict, ifnone
from fastcore.docments import frontmatter
from fastcore.parallel import startthread
from .core import AgentError, agent_err


# %% ../nbs/02_tools.ipynb #561c4516
MAX_GREP_HITS = 60  # exact matches one `grep` returns; part of the Host contract

class Hit(AttrDict):
    "One search result, in the shape every backend of `Host.search` returns."
    def __init__(self, path, line=1, symbol='', text=''):
        super().__init__(path=path, line=line, symbol=symbol, text=text)
    def __repr__(self): return f'{self.path}:{self.line}  {self.symbol}  {self.text}'


# %% ../nbs/02_tools.ipynb #4c397f68
class Host:
    """The application under an agent.

    Every method may raise; the tools in `tools.py` catch and report rather than let an
    exception end a turn. Methods that cannot be supported should raise
    `NotImplementedError`, which the tool list reads as "do not offer this tool" -- an
    agent told about a tool that always fails is worse off than one never told about it.
    """

    # -- where it is allowed to be -------------------------------------------
    @property
    def roots(self):
        "The open folders, as absolute paths. The agent is told about these and confined to them."
        raise NotImplementedError

    def check(self, path, must_exist=False, reading=False):
        """Resolve `path` and refuse anything outside `roots`, returning a `Path`.

        This is the single chokepoint. exhash and fossick both write to disk on their own
        account, so each is handed a path this has already approved rather than a path the
        model supplied. Every other method here may assume its argument came through here.

        `reading=True` says the caller will only *read* what comes back, and it is the one
        case a host may answer for a path outside `roots` -- see `LocalHost(read_outside=)`.
        A host that does not take the flag is never sent it: the tools resolve read-only
        paths through `readable`, which looks at the signature first.
        """
        raise NotImplementedError

    def walk(self):
        "Every readable file under the open folders."
        raise NotImplementedError

    def read(self, path):
        "One file's text, or None when it cannot be read."
        raise NotImplementedError

    def write(self, path, text):
        "Write `text` to `path`, through the same sandbox `check` enforces. Returns the path written."
        raise NotImplementedError

    def text_at(self, path):
        """One file as a single diffable document, `''` when it does not exist yet, None on error.

        Distinct from `read` because a notebook diffs as cell sources rather than as
        nbformat JSON, and because a file the agent is about to create must diff as a pure
        addition instead of as an error. This is what `Agent.changes()` compares.
        """
        raise NotImplementedError

    # -- seeing the code -----------------------------------------------------
    def search(self, query, limit=20):
        "Search the code index for `query`, returning `Hit`s. Semantic if an index exists, literal if not."
        raise NotImplementedError

    def peers(self, path, line, limit=20):
        "Code shaped like whatever is defined at `path`:`line` -- every place a pattern was already used."
        raise NotImplementedError

    def symbols(self, path):
        "The defs and classes in one file, as `Hit`s whose `score` is the indent depth."
        raise NotImplementedError

    def grep(self, pattern, path_filter='', regex=True, ignore_case=False, limit=MAX_GREP_HITS):
        """Every line under the open folders matching `pattern` exactly, as `Hit`s -- or None.

        The literal counterpart to `search`, and a separate capability because it has a
        different requirement: `search` may answer with what is *like* the query, and this
        must not miss. A host with a fast exact matcher -- ripgrep, an editor's own index --
        answers here. None means "I have none", and the tool falls back to walking the
        folders and reading every file, which is correct and an order of magnitude slower.
        """
        return None

    @property
    def search_note(self):
        "Which engine answered, and anything it wants to say about why. Shown when a search finds nothing."
        return ''

    # -- reading the web -----------------------------------------------------
    def web_search(self, query, n=20):
        "Search the web; returns objects with `.title` and `.url`."
        raise NotImplementedError

    def read_url(self, url, remember=True):
        "One page as markdown; `remember=False` keeps sensitive/low-quality results ephemeral."
        raise NotImplementedError

    def research(self, query):
        "Search and read the top results into one cited digest. Slower than `web_search`."
        raise NotImplementedError

    @property
    def research_note(self): return ''

    # -- durable research memory --------------------------------------------
    def memory_search(self, query, limit=8):
        "Search remembered pages as whole tree sections, returning structured rows."
        raise NotImplementedError

    def memory_tree(self, document=''):
        "The heading tree for remembered documents; an empty document lists every root."
        raise NotImplementedError

    def memory_read(self, node_id):
        "Read one remembered section and its children by stable node id."
        raise NotImplementedError

    def memory_topics(self, limit=12):
        "Labelled semantic clusters across remembered research."
        raise NotImplementedError

    def memory_forget(self, doc_id):
        "Purge one remembered document and all derived tree/chunk/vector data."
        raise NotImplementedError

    def ask(self, question, ref=None, instruction='', **kw):
        """Answer `question` out of remembered research, with citations, as a dict.

        A model call inside a tool call, which the harness otherwise avoids -- justified here by
        the same arithmetic as `delegate`: the alternative is every section of every candidate
        document arriving in the caller's context so it can read them itself.

        It is also the only way to answer out of material the caller must not see. A host whose
        store holds private documents answers those on a model that is not the caller, and
        returns what that model was willing to say.
        """
        raise NotImplementedError

    # -- standing interests --------------------------------------------------
    # Memory above is what has already been read. This is what the agent has arranged to
    # read *later*. A watch is a job the host re-runs on an interval; `poll` is the tick a
    # scheduler, a cron or a frontend calls. A reminder is the degenerate case -- a watch
    # whose action is simply to file its own text back into memory when it comes due --
    # and it is here rather than in the frontend because the thing being reminded of is
    # usually the thing that was remembered, and both should live in one store.
    def remember(self, text, title=None, tags=()):
        "File `text` into durable memory as a note. Returns the document record."
        raise NotImplementedError

    def watch(self, target, action='remind', every='1d', note=None, **params):
        "Register a recurring job. `target` is a URL, a query, or the text of a reminder."
        raise NotImplementedError

    def watches(self, due_only=False):
        "Every registered watch, soonest first. `due_only` keeps the ones that have come due."
        raise NotImplementedError

    def unwatch(self, watch_id):
        "Delete one watch. Whatever it already filed stays in memory."
        raise NotImplementedError

    def poll(self):
        """Run every watch that is due and report what fired.

        One failing watch must not stop the rest: a host implementing this records the error
        on the row and carries on, because a dead URL should not silence a reminder.
        """
        raise NotImplementedError

    @property
    def watch_actions(self):
        "The `action` values this host's `watch` will accept."
        return ('remind',)

    # -- notebooks -----------------------------------------------------------
    # The harness deliberately does not own a notebook representation. exhash addresses
    # cells by path and id without one, so only the two operations that genuinely need to
    # know what a notebook *is* are delegated here.
    def nb_cells(self, path):
        "`[(id, cell_type, first_line)]` for one notebook."
        raise NotImplementedError

    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        "Insert a cell (-1 appends), creating the notebook if needed. Returns the new cell's id."
        raise NotImplementedError

    # -- the live session ----------------------------------------------------
    def run_python(self, code):
        """Run `code` in the user's live namespace under whatever restrictions the host imposes.

        The contract the agent is briefed on: read anything, bind results to new names,
        never rebind or delete the owner's. Enforcing it is the host's job -- the harness
        only promises to tell the model about it.
        """
        raise NotImplementedError

    def inspect_python(self, code, scope='isolated'):
        """Run `code` against the live namespace without touching what the user has.

        Two scopes, and the difference is the interpreter you get rather than the safety you
        get -- both protect the owner's variables, by different means:

        - `'isolated'` runs in an allowlist sandbox on a *copy*. Attribute reads and builtins
          work; most library method calls are refused. Nothing can reach the real namespace
          at all, which is why it is the default and why it needs no trust.
        - `'overlay'` runs the real interpreter against the real namespace under an AST
          policy: the agent may read anything and bind its own names, which persist in its
          own layer, and cannot delete, rebind in place, or mutate the owner's. `list(df.columns)`
          and `df.head().to_dict()` work here; in the sandbox they do not.

        A host may refuse `'overlay'` (see `scopes`) and fall back to isolated, which is what
        a locked-down deployment does. Under a concurrent kernel either scope runs *alongside*
        a busy cell rather than queueing behind it.
        """
        raise NotImplementedError

    @property
    def scopes(self):
        "The scopes `inspect_python` will actually honour, most trusted last."
        return ('isolated',)

    @property
    def kernel_kind(self):
        """What runs the live namespace, and whether it can execute concurrently.

        `'ipymini'` means an inspection can run while a cell is busy; anything else means
        it queues behind whatever the kernel is already doing. The agent is told which,
        because "read the dataframe" is good advice under one and a way to hang the session
        under the other.
        """
        return 'ipykernel'

    @property
    def concurrent(self): return self.kernel_kind == 'ipymini'

    def list_vars(self):
        "What is in the live namespace: name, type, and a short value, one per line."
        raise NotImplementedError

    def terminal_text(self, lines=200):
        "What the IDE's terminal has printed. Read-only: this shows what the user ran, it cannot run anything."
        raise NotImplementedError

    # -- running a command ---------------------------------------------------
    def run_cmd(self, command, cwd=None, timeout=120):
        """Run `command` in a shell and return `(exit_code, combined_output)`.

        This is the capability the harness went longest without, and its absence was the
        single biggest reason the loop did not converge: an agent that can edit but cannot
        run `pytest` has no way to find out whether the edit was right, so it reports
        success instead of checking. Everything else here answers questions about the
        code; this is the only thing that can contradict the model.

        Contract a host must keep, because the tool trusts it:

        - `cwd` is resolved through `check`, so a command cannot be started outside the
          open folders. Confining the *working directory* is not confining the command --
          a shell can still name any path -- which is exactly why `run_shell` is in
          `WRITE_TOOLS` and goes to a person for approval.
        - stdout and stderr come back interleaved, in one string, as the person would see
          them. A failing test is its traceback; splitting the streams loses the order.
        - `timeout` is enforced and the whole process *group* is killed on expiry, or a
          hung `pytest -f` keeps a worker forever.
        - It returns a non-zero exit code rather than raising. A failed command is a
          result, not an exception; the model needs to read it.
        - An **empty** command is a no-op returning `(0, '')` and must not spawn anything.
          That is how `tools_for` asks "can you run commands?" without running one.
        """
        raise NotImplementedError

    @property
    def shell_note(self):
        "How commands are run here (the interpreter, the default directory), or why they are not."
        return ''

    # -- what this host can do -----------------------------------------------
    @property
    def capabilities(self):
        """Which tool groups this host supports, for the ones it can answer without being asked to prove it.

        `tools_for` normally probes a group with a harmless call, which is right when the
        answer is cheap. It is wrong when the answer is behind the very thing the probe
        would start: `VaultHost` opens its vault -- an embedding model -- in a background
        thread precisely so building the tool list does not wait for it, and then
        `memory_tree('')` waits for it anyway, on the first `Agent.tools` access.

        Return `{group: bool}` for the groups this host *knows* its answer to, and leave the
        rest out; anything absent is probed exactly as before. The names are the tool group
        functions: `notebook`, `web`, `memory`, `watch`, `session`, `shell`. A `False` is as
        useful as a `True` -- it drops a group without constructing whatever would have
        raised `NotImplementedError` on the way to saying so.
        """
        return {}

    # -- the person ----------------------------------------------------------
    @property
    def approvals(self):
        "The `Approvals` this host uses to put a write in front of a person, or None to approve everything."
        return None

    def note(self, text):
        "Tell the user something out of band (a status line). Never blocks; a host may drop it."
        pass

# %% ../nbs/02_tools.ipynb #2760c808
class NullHost(Host):
    "A host with nothing behind it: every capability absent, so the harness runs bare in a test."

    def __init__(self, roots=()): self._roots = [str(r) for r in roots]

    @property
    def roots(self): return self._roots

    def check(self, path, must_exist=False, reading=False):
        from pathlib import Path
        return Path(path)

    def walk(self): return []
    def read(self, path): return None
    def write(self, path, text): raise NotImplementedError
    def text_at(self, path): return None
    def search(self, query, limit=20): return []
    def peers(self, path, line, limit=20): return []
    def symbols(self, path): return []
    def web_search(self, query, n=20): return []
    def read_url(self, url, remember=True): return None
    def research(self, query): return ''
    def memory_search(self, query, limit=8): raise NotImplementedError
    def memory_tree(self, document=''): raise NotImplementedError
    def memory_read(self, node_id): raise NotImplementedError
    def memory_topics(self, limit=12): raise NotImplementedError
    def memory_forget(self, doc_id): raise NotImplementedError
    def remember(self, text, title=None, tags=()): raise NotImplementedError
    def watch(self, target, action='remind', every='1d', note=None, **params): raise NotImplementedError
    def watches(self, due_only=False): raise NotImplementedError
    def unwatch(self, watch_id): raise NotImplementedError
    def poll(self): raise NotImplementedError
    def nb_cells(self, path): raise NotImplementedError
    def nb_add_cell(self, path, source, index=-1, cell_type='code'): raise NotImplementedError
    def run_python(self, code): raise NotImplementedError
    def run_cmd(self, command, cwd=None, timeout=120): raise NotImplementedError
    def inspect_python(self, code, scope='isolated'): raise NotImplementedError
    def list_vars(self): raise NotImplementedError
    def terminal_text(self, lines=200): raise NotImplementedError

# %% ../nbs/02_tools.ipynb #602dbaf6
SANDBOX = 'path is outside the open folders'
SECRET = 'path holds credentials and is never read'
NO_ROOTS = 'no folders are open, so no path is inside them'

#: Never opened, even when a host is allowed to read outside its folders. Opening the
#: sandbox is a decision about *source* -- somebody's site-packages, a sibling checkout, a
#: log under /var -- and not about their keys, which a turn would put verbatim into a cloud
#: model's context. Matched with `fnmatch` against the resolved path, so `*` crosses `/`.
DENY = ('*/.ssh/*', '*/.aws/*', '*/.gnupg/*', '*/.config/gcloud/*', '*/.netrc',
        '*/.git-credentials', '*/.codex/auth.json', '*/.claude/.credentials.json',
        '*/.env', '*/.env.*', '*/id_rsa*', '*/id_ed25519*', '*.pem', '*.key', '*.p12')
SKIP_DIRS = frozenset({'.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', 'node_modules',
                       '.ipynb_checkpoints', '.pytest_cache', '.mypy_cache', '_docs', '_proc',
                       'dist', 'build', '.quarto', '.idea', '.attic'})
SKIP_SUFFIXES = frozenset({'.pyc', '.pyo', '.so', '.dylib', '.dll', '.a', '.o', '.zip', '.gz',
                           '.whl', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.parquet',
                           '.sqlite', '.db', '.bin', '.safetensors', '.gguf'})
MAX_FILE = 2_000_000      # bytes; a file larger than this is data, not source
MAX_VARS = 200
LD_CHARS = 4000           # of a page's JSON-LD to keep; enough for a product, not a catalogue

_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def denied(path, patterns=DENY):
    "Whether `path` is one of the things reading outside the open folders still must not open."
    from fnmatch import fnmatch
    s = Path(path).as_posix()
    return any(fnmatch(s, pat) for pat in patterns)

def _md_doc(d):
    "One of fossick's document readers' results as markdown: the fields it has, then its text."
    if isinstance(d, str): return d
    if not isinstance(d, dict): return str(d or '')
    head = [f'**{k}**: {v}' for k in ('title', 'authors', 'published', 'channel', 'duration', 'link')
            if (v := d.get(k)) not in (None, '', [], {})]
    body = next((str(d[k]) for k in ('source', 'text', 'content', 'summary') if d.get(k)), '')
    return '\n'.join(head + [''] + [body]).strip() if head else body.strip()

def _fuse(legs, limit):
    """Merge ranked `Hit` lists by reciprocal rank fusion via `litesearch.rrf_all`.

    Same primitive `Vault.federate` uses. Legs share no score scale, so rank is the only
    common currency; identity is `path:line`. One leg is returned as-is.
    """
    legs = [list(l) for l in legs if l]
    if not legs: return []
    if len(legs) == 1: return legs[0][:limit]
    by_key, lists = {}, []
    for leg in legs:
        rows = []
        for h in leg:
            key = f'{h.path}:{h.line}'
            by_key.setdefault(key, h)
            rows.append({'_fid': key})
        lists.append(rows)
    try:
        from litesearch import rrf_all
        fused = rrf_all(lists, id_key='_fid', limit=limit)
    except Exception: return legs[0][:limit]
    return [by_key[r['_fid']] for r in fused if r.get('_fid') in by_key]

def ld_json(html):
    "The `schema.org` JSON-LD blocks in `html` -- where a page states its price, author or rating."
    out = []
    for m in _LD.finditer(html or ''):
        try: out.append(json.loads(m.group(1)))
        except Exception: pass
    return out

class LocalHost(Host):
    """A host over real folders on disk, and a live Python namespace in this process.

    This is the reference implementation of `Host`: enough of one to run the agent from a
    terminal, from an MCP server, or from a test, with no IDE anywhere. Capabilities it
    genuinely cannot provide raise `NotImplementedError`, so `tools_for` drops them rather
    than offering the model a tool that always fails.
    """

    def __init__(self,
                 roots=('.',),          # the folders the agent is confined to
                 ns=None,               # the live namespace; a fresh dict when None
                 approvals=None,        # an `Approvals`, or None to gate nothing
                 note=None,             # callable for out-of-band status lines
                 web=True,              # wire the web tools to fossick when it is installed
                 index=True,            # start a Kosha sync for every open root
                 rerank=True,           # reorder Kosha's hits with its flashrank cross-encoder
                 rerank_model=None,     # flashrank model name; None is its fast default
                 read_outside=False,    # let read-only tools name any path on this machine
                 deny=DENY):            # what `read_outside` still refuses to open
        self._roots = [str(Path(r).expanduser().resolve()) for r in roots]
        self.ns = ifnone(ns, {'__name__': '__main__'})
        self._approvals, self._note, self.web = approvals, note, web
        self.read_outside, self.deny = bool(read_outside), tuple(deny or ())
        self.transcript = []           # what this process has printed, for `read_terminal`
        self._koshas, self._index_errors, self._index_thread = [], [], None
        self._pending = list(self._roots)     # roots whose sync has not returned yet
        self.rerank, self.rerank_model, self._rerank_note = bool(rerank), rerank_model, ''
        if index: self.sync_index()

    def sync_index(self, wait=False, force=False):
        """Run `Kosha.sync` for every open root, once, in a daemon thread.

        Starts at construction so indexing overlaps model startup. Each root is published as
        soon as *its* sync returns, so a small folder next to a large one is searchable
        without waiting for the large one. Pass `graph=True` and `in_parallel=True`: `_semantic`
        asks `context` for graph expansion, and the three SQLite stores are safe to fill together.
        """
        if self._index_thread is None or not self._index_thread.is_alive():
            def run():
                try:
                    os.environ.setdefault('TQDM_DISABLE', '1')  # kosha's tqdm even with verbose=False
                    from kosha import Kosha
                except Exception as e:
                    self._index_errors.append(agent_err(e)); self._pending = []; return
                for root in list(self._roots):
                    try:
                        k = Kosha(dir=Path(root))
                        k.sync(dir=Path(root), verbose=False, force=force, pyproject=True,
                               in_parallel=True, graph=True)
                        self._koshas.append(k)
                    except Exception as e: self._index_errors.append(agent_err(e))
                    finally:
                        try: self._pending.remove(root)
                        except ValueError: pass
            self._index_thread = startthread(run, daemon=True)
            self._index_thread.name = 'ramabana-kosha-sync'
        if wait: self._index_thread.join()
        return self

    @property
    def index_ready(self):
        "Whether *every* open folder is indexed. `indexed` is the per-folder answer `search` uses."
        return bool(self._koshas) and not self._pending

    @property
    def indexed(self):
        "The folders whose index is built and searchable now. The rest are still syncing."
        return [str(getattr(k, 'root', '')) for k in list(self._koshas)]

    def wait_index(self, timeout=None):
        "Wait for the automatic Kosha sync. Returns whether semantic search is ready."
        if self._index_thread is not None: self._index_thread.join(timeout)
        return self.index_ready

    @property
    def roots(self): return list(self._roots)

    def check(self, path, must_exist=False, reading=False):
        """Resolve `path` and refuse anything outside `roots`. Every other method assumes this ran.

        With `read_outside` on, a *read* may name any path on the machine and a write may
        not, which is the asymmetry that makes the option worth having: the reason to open
        the sandbox is that the answer is in a sibling checkout or somebody's site-packages,
        and none of those are reasons to edit them. Enumeration stays confined too -- `walk`,
        and therefore `grep` and `list_files`, never leave the open folders -- so reading
        outside is always by a path the model had to already know.
        """
        p = Path(path).expanduser()
        if not self._roots: raise AgentError(f'{NO_ROOTS}: {p}')  # empty roots must refuse, not IndexError
        if not p.is_absolute(): p = Path(self._roots[0])/p
        p = p.resolve()  # collapse `..` and out-of-root symlinks before comparing
        if not any(p == Path(r) or Path(r) in p.parents for r in self._roots):
            if not (reading and self.read_outside): raise AgentError(f'{SANDBOX}: {p}')
            if denied(p, self.deny): raise AgentError(f'{SECRET}: {p}')
        if must_exist and not p.exists(): raise AgentError(f'no such file: {p}')
        return p

    @property
    def roots_note(self):
        "How paths are resolved here, in one line, for the briefing and a status bar."
        n = len(self._roots)
        return (f'{n} folder(s); reads may name any path on this machine, writes may not'
                if self.read_outside else f'{n} folder(s); nothing outside them is readable')

    def _walk(self, root):
        "Files under `root`, skipping the same generated dirs/suffixes `grep` covers."
        try:
            from rgapi import fd
            rows = fd(root=root, skip_dir=sorted(SKIP_DIRS), max_filesize=MAX_FILE,
                      exclude=[f'*{s}' for s in sorted(SKIP_SUFFIXES)])
            for p in rows:
                p = Path(p)
                if not p.is_absolute(): p = Path(root)/p
                if p.is_symlink() or not p.is_file(): continue
                yield p
            return
        except Exception: pass
        for p in sorted(Path(root).rglob('*')):
            if any(part in SKIP_DIRS for part in p.parts): continue
            if not p.is_file() or p.is_symlink(): continue
            if p.suffix.lower() in SKIP_SUFFIXES: continue
            try:
                if p.stat().st_size > MAX_FILE: continue
            except OSError: continue
            yield p

    def walk(self):
        return [p for r in self._roots for p in self._walk(r)]

    def read(self, path):
        try: return self.check(path, must_exist=True, reading=True).read_text(encoding='utf-8')
        except Exception: return None

    def write(self, path, text):
        p = self.check(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(text), encoding='utf-8')
        return str(p)

    def text_at(self, path):
        """One file as a diffable document: a notebook as its cell sources, anything else as text.

        `''` rather than None for a file that does not exist yet, so a file the agent is
        about to create diffs as a pure addition instead of as an error.
        """
        try: p = self.check(path)
        except Exception: return None
        if not p.exists(): return ''
        if p.suffix == '.ipynb':
            try:
                from fastcore.nbio import read_nb
                return '\n\n'.join(''.join(c.source) for c in read_nb(p).cells)
            except Exception: return None
        try: return p.read_text(encoding='utf-8')
        except Exception: return None

    # -- seeing the code -----------------------------------------------------
    def _rg(self, query, limit, regex=False, ignore_case=False, path_filter='', per_file=5, every_file=False):
        """Search through `rgapi.rg` -- the same engine `Vault.grep` uses.

        `every_file=True` matches what `walk` yields (hidden files, ignore `.gitignore`, skip
        generated dirs). `search`'s literal leg keeps ripgrep defaults so build trees stay out.
        """
        try: from rgapi import rg
        except Exception: return None
        pattern = query if regex else re.escape(query)
        kw = dict(case_sensitive=(False if ignore_case else None), smart_case=not ignore_case,
                  max_filesize=MAX_FILE, timeout_ms=20_000)
        if path_filter: kw['glob'] = f'*{path_filter}*'
        if every_file:
            kw.update(hidden=True, ignore=False, skip_dir=sorted(SKIP_DIRS),
                      exclude=[f'*{s}' for s in sorted(SKIP_SUFFIXES)])
        hits, counts = [], {}
        try:
            for root in self._roots:
                # pull enough rows to honour per-file caps, then trim to `limit`
                pull = None if not per_file else max(limit * 8, limit)
                for m in rg(pattern, root=root, max_results=pull, **kw):
                    if getattr(m, 'kind', 'match') != 'match': continue
                    path = Path(m.path)
                    if not path.is_absolute(): path = Path(root)/path
                    path_s = str(path)
                    if per_file:
                        n = counts.get(path_s, 0)
                        if n >= per_file: continue
                        counts[path_s] = n + 1
                    hits.append(Hit(path_s, int(m.line_number), '', (m.line or '').strip()[:200]))
                    if len(hits) >= limit: return hits
        except Exception: return None
        return hits

    def grep(self, pattern, path_filter='', regex=True, ignore_case=False, limit=MAX_GREP_HITS):
        "Exact matching through ripgrep. None when `rgapi` is unavailable; the tool then reads files itself."
        return self._rg(pattern, limit, regex=regex, ignore_case=ignore_case,
                        path_filter=path_filter, per_file=None, every_file=True)

    def _ranked(self, call, **kw):
        """One Kosha context call, reordered by its cross-encoder when reranking is on and working.

        `rerank=` widens the retrieval limit and reorders what comes back with a flashrank
        cross-encoder -- the cheapest relevance win available to the most-called tool, and it
        was sitting unused on both `repo_context` and `context`.

        flashrank fetches its model the first time it is asked, so the first search on a
        machine without one cached is also the search that finds out. That is not a search
        failure -- unranked hits are exactly what this host returned for its whole life
        before -- so it falls back once, says so in `search_note`, and stops asking.
        """
        if self.rerank:
            try: return call(rerank=True, rerank_model=self.rerank_model, **kw)
            except Exception as e:
                self.rerank = False
                self._rerank_note = f'; reranking off ({agent_err(e)})'
        return call(**kw)

    def _semantic(self, query, limit):
        "Kosha hybrid results (repo + env + graph) as the Host's stable `Hit` shape."
        koshas = list(self._koshas)
        if not koshas: return []
        out, seen = [], set()
        for k in koshas:
            try:
                rows = self._ranked(k.context, q=query, limit=limit, repo=True, env=True,
                                    graph=True, columns='content,metadata')
            except Exception as e:
                self._index_errors.append(agent_err(e)); continue
            for row in rows:
                row = dict(row)
                meta = row.get('metadata') or {}
                if isinstance(meta, str):
                    try: meta = ast.literal_eval(meta)
                    except Exception: meta = {}
                path = str(meta.get('path') or row.get('path') or '')
                line = int(meta.get('lineno') or 1)
                key = (path, line)
                if key in seen: continue
                seen.add(key)
                symbol = meta.get('mod_name') or meta.get('name') or ''
                text = ' '.join(str(row.get('content') or '').split())[:240]
                out.append(Hit(path, line, str(symbol), text))
                if len(out) >= limit: return out
        return out

    def _scan(self, query, limit):
        "Every matching line, by reading the files. What is left when there is no index and no ripgrep."
        hits = []
        for p in self.walk():
            try: text = p.read_text(encoding='utf-8')
            except Exception: continue
            if query not in text: continue
            for i, line in enumerate(text.splitlines(), 1):
                if query in line:
                    hits.append(Hit(str(p), i, '', line.strip()[:200]))
                    if len(hits) >= limit: return hits
        return hits

    def search(self, query, limit=20):
        """The code index and the literal scan, fused by rank rather than tried in order.

        Kosha answers "what is this like"; ripgrep answers "where is this exact string". Both
        run, and `litesearch.rrf_all` merges them -- the same RRF `Vault.federate` uses.
        While the index is still syncing, the literal leg is usually the only one with hits.
        """
        if not (query or '').strip(): return []
        rg = self._rg(query, limit)
        if (hits := _fuse([self._semantic(query, limit), rg or []], limit)): return hits
        # `_rg` is None when rgapi is unavailable; `[]` when it ran and found nothing.
        return [] if rg is not None else self._scan(query, limit)

    @property
    def search_note(self):
        n, tot = len(self._koshas), len(self._roots)
        if n:
            where = f'{n} of {tot} folder(s)' if self._pending else f'{tot} folder(s)'
            return f'Kosha semantic + keyword index over {where} and environment fused with ripgrep{self._rerank_note}'
        if self._index_errors: return f'Kosha unavailable ({self._index_errors[-1]}); literal fallback'
        return 'Kosha sync in progress; literal fallback via ripgrep'

    def _defs(self, path):
        "Every def/class in one file as `(line, qualified_name, depth)`, by parsing rather than grepping."
        src = self.read(path)
        if src is None: return []
        try: tree = ast.parse(src)
        except SyntaxError: return []
        out = []
        def walk(node, prefix='', depth=0):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = f'{prefix}{child.name}'
                    out.append((child.lineno, name, depth))
                    walk(child, f'{name}.', depth + 1)
        walk(tree)
        return out

    def symbols(self, path):
        "The defs and classes in one file, as `Hit`s whose `score` is the indent depth."
        p = self.check(path, reading=True)
        out = []
        for line, name, depth in self._defs(p):
            h = Hit(str(p), line, name, '')
            h.score = depth
            out.append(h)
        return out

    def peers(self, path, line, limit=20):
        """Every other place the symbol defined at `path`:`line` is mentioned.

        Not a semantic index -- this host has none -- but the useful half of one: the call
        sites and overrides of the thing under the cursor, which is what "where else do we
        do this" usually means.
        """
        p = self.check(path, reading=True)
        defs = self._defs(p)
        name = next((n for ln, n, _ in sorted(defs, key=lambda d: -d[0]) if ln <= int(line)), None)
        if name is None: return []
        leaf = name.split('.')[-1]
        return [h for h in self.search(leaf, limit * 2)
                if not (str(h.path) == str(p) and h.line == int(line))][:limit]

    # -- notebooks -----------------------------------------------------------
    def nb_cells(self, path):
        from fastcore.nbio import read_nb
        nb = read_nb(self.check(path, must_exist=True, reading=True))
        return [(c.get('id', ''), c.cell_type, ''.join(c.source)) for c in nb.cells]

    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        from fastcore.nbio import read_nb, write_nb, mk_cell, dict2nb
        p = self.check(path)
        nb = read_nb(p) if p.exists() else dict2nb({'cells': [], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5})
        cell = mk_cell(source, cell_type)
        if not cell.get('id'): cell['id'] = uuid.uuid4().hex[:8]
        nb.cells.append(cell) if index < 0 else nb.cells.insert(int(index), cell)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_nb(nb, p)
        return cell['id']

    # -- the live session ----------------------------------------------------
    def _exec(self, code, ns):
        """Run `code` in `ns`, returning printed output plus the last expression's value.

        Split into statements-then-final-expression so `df.shape` answers with the shape
        instead of with nothing, which is what makes this usable for looking at state.
        """
        import contextlib, io
        buf = io.StringIO()
        tree = ast.parse(str(code))
        last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            if tree.body: exec(compile(tree, '<agent>', 'exec'), ns)
            value = eval(compile(ast.Expression(last.value), '<agent>', 'eval'), ns) if last else None
        out = buf.getvalue()
        if value is not None: out += ('' if not out or out.endswith('\n') else '\n') + repr(value)
        return out.strip() or '(no output)'

    def run_python(self, code):
        "Run `code` in the live namespace. Failures come back as text: a tool cannot usefully raise."
        try: return self._exec(code, self.ns)
        except Exception as e: return f'{agent_err(e)}'

    def inspect_python(self, code, scope='isolated'):
        "Run `code` against a *copy* of the namespace, so nothing the user made can move."
        if scope not in self.scopes: return f'this host only honours {self.scopes}'
        try: return self._exec(code, dict(self.ns))
        except Exception as e: return f'{agent_err(e)}'

    @property
    def scopes(self):
        "Isolated only. Overlay needs an AST policy over the real namespace, which belongs to an IDE."
        return ('isolated',)

    @property
    def kernel_kind(self): return 'inprocess'

    # -- running a command ---------------------------------------------------
    def run_cmd(self, command, cwd=None, timeout=120):
        """Run `command` in a shell under one of the open folders.

        Without this, an agent driven from the terminal or over MCP can edit a project but
        never find out whether the edit was right -- which is the failure `run_shell`'s
        docstring describes, and there is no reason a real filesystem host should have it.

        The process is started in its own group and the *group* is killed on timeout, so a
        command that spawns children (`pytest -n`, a build) cannot leave one behind. stdout
        and stderr are interleaved, as a person would see them.
        """
        import subprocess
        if not str(command or '').strip(): return 0, ''   # the capability probe
        if not (cwd or self._roots): raise AgentError(NO_ROOTS)
        d = self.check(cwd) if cwd else Path(self._roots[0])
        if not d.is_dir(): raise AgentError(f'not a directory: {d}')
        p = subprocess.Popen(str(command), shell=True, cwd=str(d), text=True, errors='replace',
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True)
        try: out, _ = p.communicate(timeout=max(1, int(timeout)))
        except subprocess.TimeoutExpired:
            import os, signal
            try: os.killpg(p.pid, signal.SIGKILL)
            except Exception: p.kill()
            out, _ = p.communicate()
            return 124, (out or '') + f'\n[killed after {int(timeout)}s]'
        return p.returncode, out or ''

    @property
    def shell_note(self):
        return f'shell, in {self._roots[0]}' if self._roots else 'no folder to run a command in'

    def list_vars(self):
        rows = []
        for k, v in list(self.ns.items())[:MAX_VARS]:
            if k.startswith('_') or callable(v) or isinstance(v, type(ast)): continue
            try: short = repr(v)
            except Exception: short = '<unreprable>'
            rows.append(f'{k:20} {type(v).__name__:12} {short[:60]}')
        return '\n'.join(rows)

    def terminal_text(self, lines=200):
        "What this process has printed, when the application records it in `transcript`."
        return '\n'.join(str(x) for x in self.transcript[-int(lines):])

    # -- the web -------------------------------------------------------------
    def _fossick(self):
        if not self.web: raise NotImplementedError
        try:
            import fossick
            return fossick
        except Exception: raise NotImplementedError

    def web_search(self, query, n=20):
        """Search the web through fossick.

        An empty query answers `[]` after checking only that fossick imports, because that is
        how `tools_for` probes for this capability -- and a tool list that cannot be built
        without a network round trip is a tool list that fails on a train.
        """
        fossick = self._fossick()
        if not str(query).strip(): return []
        # `n` to fossick, not a slice afterwards: its own default is 10, so asking for twenty
        # results and truncating twenty to twenty quietly returned ten.
        rows = fossick.search(str(query), n=int(n))
        return [AttrDict(title=str(r.get('title', '')), url=str(r.get('href') or r.get('url', ''))) for r in rows]

    #: Extracted characters below which a page did not really load. A site that turns away
    #: scrapers does not answer 403 -- it answers 200 with an empty shell, so escalating on
    #: the status code never fires and fossick's own `auto=` tier stops at `plain`.
    THIN_PAGE = 400

    #: URLs that are not really pages, and the fossick reader that knows what each one *is*.
    #: Fetched as a page, a GitHub blob is chrome and line numbers wrapped around the file, an
    #: arxiv abstract is not the paper, and a YouTube watch page does not contain its
    #: transcript at all. `read_url`'s docstring has promised the first two all along.
    #: `read_gh_repo` is deliberately not here: cloning a repository is not reading a page,
    #: and it is reached by name, not by handing this tool a URL.
    READERS = (
        (re.compile(r'https?://(www\.)?github\.com/[^/]+/[^/]+/(blob|raw)/', re.I), 'read_gh_file', {}),
        (re.compile(r'https?://(www\.)?arxiv\.org/(abs|pdf)/', re.I), 'read_arxiv', dict(save_pdf=False, source=True)),
        (re.compile(r'https?://(www\.)?(youtube\.com/watch|youtu\.be/)', re.I), 'read_yt', {}),
    )

    def read_url(self, url, remember=True):
        """One page as markdown: the prose, and the structured data the prose leaves out.

        Some URLs are not pages, and fossick ships a reader for each: `READERS` routes those
        first, which is what this docstring has been promising since it was written while the
        implementation was a plain fetch.

        For everything else, two things go wrong on a modern page and neither shows up as an
        error. It renders in the browser, so a plain fetch returns a shell. `auto=True` is
        fossick's answer -- plain, then heavy, then stealthy, then the logged-in Chrome, one
        tier at a time, on its own bot-block detection. Hand-rolling plain -> stealthy here
        skipped the tier that fixes almost all of these: most pages that need a browser need
        *rendering*, not evasion, and a stealth Chrome costs ten seconds.

        `auto`'s detection cannot see the other shape of the same failure -- a 200 whose body
        is an empty shell, which is what a site that turns scrapers away actually returns -- so
        a page that extracts to nothing is escalated here as well, and from the cheap tier up.

        And a page's *facts* live in `schema.org` JSON-LD rather than in its prose, so
        readability extraction on a product page faithfully keeps the ingredient list and
        throws the price away. That is a standard, not a selector for one shop.
        """
        fossick = self._fossick()
        for rx, name, kw in self.READERS:
            if not rx.search(str(url)) or (reader := getattr(fossick, name, None)) is None: continue
            try: text = _md_doc(reader(str(url), **kw))
            except Exception as e:
                # A reader that cannot answer is not a URL that cannot be read: the abstract
                # page is worse than the paper, and better than nothing.
                self.note(f'{name} could not read {url} ({agent_err(e)}); fetching the page')
                break
            if text.strip(): return AttrDict(text=text, url=str(url))
            break
        page = fossick.fetch(str(url), auto=True)
        text = str(fossick.to_md(page) or '') if page is not None else ''
        if len(text.strip()) < self.THIN_PAGE:
            for opts in ({'heavy': True}, {'stealthy': True}):
                try: heavy = fossick.fetch(str(url), **opts)
                except Exception: continue
                if len((got := str(fossick.to_md(heavy) or '')).strip()) >= self.THIN_PAGE:
                    page, text = heavy, got
                    break
        if (ld := ld_json(getattr(page, 'html_content', '') or '')):
            text = f'<structured-data>\n{json.dumps(ld)[:LD_CHARS]}\n</structured-data>\n\n{text}'
        return None if not text.strip() else AttrDict(text=text, url=str(url))

    def research(self, query):
        """The cited corpus fossick assembled, and not the record it assembled it from.

        `fossick.research` answers `{query, sources, digest, dropped}`, where `digest` *is*
        the cited markdown and `sources` is the same markdown again, per page. Stringifying
        the whole dict sent the model both copies wrapped in Python dict syntax.
        """
        return str((self._fossick().research(str(query)) or {}).get('digest') or '')

    @property
    def research_note(self): return 'fossick' if self.web else 'web access is switched off'

    # -- the person ----------------------------------------------------------
    @property
    def approvals(self): return self._approvals

    def note(self, text):
        self.transcript.append(str(text))
        if self._note:
            try: self._note(str(text))
            except Exception: pass


# %% ../nbs/02_tools.ipynb #7fe5525c
GROUP,EXTRA_MODULES,MAX_SKILL_CHARS = 'pyskills',('exhash.skill',),20_000

def _describe(text, mx=300):
    'A one-line description from a skill body: its first paragraph, collapsed.'
    body = (text or '').strip()
    if not body: return ''
    para = body.split('\n\n', 1)[0]
    one = ' '.join(para.split())
    return one if len(one) <= mx else one[:mx - 1].rstrip() + '…'

@dataclass
class Skill:
    'One skill: how to name it, when it applies, and how to get the whole text.'
    name: str
    source: str                   # 'pyskill' | 'md'
    description: str = ''
    where: str = ''               # module path or file path, shown so a person can go read it
    _text: object = field(default=None, repr=False)

    def text(self):
        'The full skill body, clipped. Never raises: a broken skill reports itself as one.'
        try: t = self._text() if callable(self._text) else (self._text or '')
        except Exception as e: return f'could not read skill {self.name}: {agent_err(e)}'
        t = str(t)
        return t if len(t) <= MAX_SKILL_CHARS else t[:MAX_SKILL_CHARS] + f'\n…[{len(t)-MAX_SKILL_CHARS} more chars]'

    def dict(self): return {'name': self.name, 'source': self.source,'description': self.description, 'where': self.where}

# %% ../nbs/02_tools.ipynb #10eb28d5
def _mod_skill(name, modpath):
    "A `Skill` for a module, without importing it until someone asks for the body."
    def load():
        from importlib import import_module
        return import_module(modpath).__doc__ or ''
    # The description does need the docstring, and there is no way to read one without
    # importing. Failing quietly is right: a package whose import breaks should cost the
    # agent one missing skill, not a session.
    try:
        from importlib import import_module
        doc = import_module(modpath).__doc__ or ''
    except Exception: return None
    if not doc.strip(): return None
    return Skill(name=name, source='pyskill', description=_describe(doc), where=modpath, _text=load)

def _pyskills():
    "Every module published under the `pyskills` entry-point group, plus the known stragglers."
    out, seen = [], set()
    try:
        from importlib.metadata import entry_points
        eps = list(entry_points(group=GROUP))
    except Exception:
        eps = []
    for ep in eps:
        mod = getattr(ep, 'value', None) or ep.name
        if mod in seen: continue
        seen.add(mod)
        if (s := _mod_skill(ep.name.split('.')[-1] or ep.name, mod)): out.append(s)
    for mod in EXTRA_MODULES:
        if mod in seen: continue
        seen.add(mod)
        if (s := _mod_skill(mod.split('.')[0], mod)): out.append(s)
    return out

def skill_dirs(roots=(), cfg=None):
    """Where SKILL.md files are looked for, in increasing precedence.

    User directories first so a project can override a personal skill of the same name --
    which is the way round that matters, since the project is the shared thing and the
    personal one is the habit.
    """
    from pathlib import Path
    ds = []
    if cfg is not None: ds.append(Path(cfg)/'skills')
    ds.append(Path.home()/'.agents'/'skills')
    for r in roots: ds += [Path(r)/'.leela'/'skills', Path(r)/'.agents'/'skills']
    return ds

def _md_skills(d):
    "Skills in one directory, following the Agent Skills layout: `<name>/SKILL.md`."
    from pathlib import Path
    d = Path(d)
    if not d.is_dir(): return []
    out = []
    for p in sorted(d.iterdir()):
        if not p.is_dir(): continue
        f = p/'SKILL.md'
        if not f.exists(): continue
        try: raw = f.read_text(encoding='utf-8')
        except Exception: continue
        meta, body = frontmatter(raw)
        out.append(Skill(name=meta.get('name') or p.name, source='md',
                         description=meta.get('description') or _describe(body),
                         where=str(f), _text=body))
    return out

def discover(roots=(), cfg=None, extra=()):
    """Every skill available to this agent, later sources winning on a name clash.

    Order is pyskills, then each skill directory in `skill_dirs` order, then `extra` (what
    an extension registered). A file beats a package deliberately: the package's skill is
    the general advice, and the one you wrote in your own repository is the correction.
    """
    by_name = {}
    for s in _pyskills(): by_name[s.name] = s
    for d in skill_dirs(roots, cfg):
        for s in _md_skills(d): by_name[s.name] = s
    for s in extra or (): by_name[s.name] = s
    return sorted(by_name.values(), key=lambda s: s.name)

# %% ../nbs/02_tools.ipynb #bfaf4907
SKILL_DESC_MAX = 160   # per skill, so one verbose description cannot crowd out the rest

def _clip_desc(s, n=SKILL_DESC_MAX):
    """One line, clipped at a word boundary.

    Descriptions are written to be *found* -- some enumerate every trigger word their author
    could think of, running to a thousand characters. In the index they only have to be
    distinguishable enough to pick, since `read_skill` then supplies the whole text.
    """
    s = ' '.join(str(s).split())
    if len(s) <= n: return s
    cut = s.rfind(' ', 0, n)
    return s[:cut if cut > 0 else n].rstrip(' .,;:\u2014-') + '\u2026'

def skill_index(skills):
    "The block that goes in the system prompt: names and clipped descriptions, never bodies."
    if not skills: return ''
    rows = '\n'.join(f'- `{s.name}` -- {_clip_desc(s.description)}' for s in skills)
    return ('\n\n## Skills\n\nKnow-how available to you. Read one with `read_skill(name)` when its '
            'description matches what you are about to do, *before* you do it -- several of these '
            'describe tools already installed in this environment, so the code they discuss is '
            'also searchable with `search_code`.\n\n' + rows)

def find(skills, name):
    """A skill by exact name, then by unique prefix, then by unique substring.

    Ambiguity returns None rather than a guess. A model that asked for `edit` and silently
    got `editskill` will read the wrong reference and then confidently do the wrong thing,
    which is worse than being told to be specific.
    """
    if not name: return None
    n = name.strip().lower()
    if (exact := [s for s in skills if s.name.lower() == n]): return exact[0]
    for pred in (lambda s: s.name.lower().startswith(n), lambda s: n in s.name.lower()):
        if len(hits := [s for s in skills if pred(s)]) == 1: return hits[0]
    return None

# %% ../nbs/02_tools.ipynb #f565d042
EVENTS = ('before_turn', 'after_turn', 'before_tool', 'after_tool', 'compact', 'approval')

# %% ../nbs/02_tools.ipynb #fa5f4616
class Registry:
    """What `setup(ext)` is handed: everything an extension may add, and nothing else.

    `host` and `agent` are exposed because an extension that cannot read a file or see the
    conversation is not worth writing. What is deliberately *not* here is any way to reach
    a backend's internals -- an extension that pokes at a litert conversation would break
    on the next model switch, and would break silently.
    """

    def __init__(self, host=None, agent=None):
        self.host, self.agent = host, agent
        self.tools, self.skills, self.commands = [], [], {}
        self.hooks = {e: [] for e in EVENTS}
        self.approve = None
        self.notes = []          # one line per extension: loaded, or why not

    # -- registration --------------------------------------------------------
    def tool(self, f):
        """Add a tool. Usable as a decorator.

        The contract is the backends' own: a plain function with type hints and a
        docstring. That docstring is what the model reads, so it is documentation and not
        a comment.
        """
        self.tools.append(f)
        return f

    def skill(self, name, text, description=''):
        "Add a skill the discovery pass would not find -- a file, a string, anything callable."
        s = Skill(name=name, source='ext', description=description or _describe(text if isinstance(text, str) else ''),
                  where='extension', _text=text)
        self.skills.append(s)
        return s

    def command(self, name, fn, help=''):
        "Add a slash command. `fn(agent, arg)` returns text for the frontend to show."
        self.commands[name.lstrip('/')] = (fn, help)
        return fn

    def on(self, event, fn):
        "Hook a harness lifecycle event. Unknown event names are an error, not a silent no-op."
        if event not in EVENTS: raise KeyError(f'unknown event {event!r}; known: {", ".join(EVENTS)}')
        self.hooks[event].append(fn)
        return fn

    def approval(self, fn):
        "Replace the approval policy wholesale. The last extension to call this wins."
        self.approve = fn
        return fn

    # -- dispatch ------------------------------------------------------------
    def fire(self, event, *args, **kw):
        "Run every hook for `event`, swallowing failures. Returns how many ran cleanly."
        n = 0
        for f in self.hooks.get(event, ()):
            try: f(*args, **kw); n += 1
            except Exception as e: self.notes.append(f'{event} hook failed: {agent_err(e)}')
        return n

# %% ../nbs/02_tools.ipynb #a90555f2
def ext_dirs(roots=(), cfg=None, project=False):
    "Where extensions are looked for. Project directories only when explicitly allowed."
    ds = []
    if cfg is not None: ds.append(Path(cfg)/'extensions')
    if project:
        for r in roots: ds.append(Path(r)/'.leela'/'extensions')
    return ds


def load(reg, roots=(), cfg=None, project=False, paths=()):
    """Run every extension found, calling its `setup(reg)`. Returns the registry.

    A file with no `setup` is loaded and left alone rather than reported as broken: that is
    how a shared helper module sitting in the same directory should behave.
    """
    files = []
    for d in ext_dirs(roots, cfg, project):
        if Path(d).is_dir(): files += sorted(p for p in Path(d).glob('*.py') if not p.name.startswith('_'))
    for p in paths or ():
        p = Path(p)
        files += sorted(p.glob('*.py')) if p.is_dir() else [p]
    for f in files:
        try: ns = runpy.run_path(str(f))
        except Exception as e:
            reg.notes.append(f'{f.name}: failed to load ({agent_err(e)})')
            continue
        fn = ns.get('setup')
        if not callable(fn):
            reg.notes.append(f'{f.name}: loaded, no setup()')
            continue
        before = (len(reg.tools), len(reg.skills), len(reg.commands))
        try: fn(reg)
        except Exception as e:
            reg.notes.append(f'{f.name}: setup() failed ({agent_err(e)})')
            continue
        d = [n - b for n, b in zip((len(reg.tools), len(reg.skills), len(reg.commands)), before)]
        reg.notes.append(f'{f.name}: {d[0]} tool(s), {d[1]} skill(s), {d[2]} command(s)')
    return reg

# %% ../nbs/02_tools.ipynb #faa16c87
# How many chars one tool result may spend, by default. Deliberately small: this is a
# budget against the *smallest* model the harness runs, and an on-device model with a
# 16k window is spent by three generous results. A host that knows it is talking to a
# large-context model raises it -- `Agent(tool_max_len=...)`, threaded into `tools_for`.
MAX_TOOL_CHARS = 6000
MAX_HITS = 20

# The tools that change something on disk, in the live session, or on the machine. Named
# as a set because that is the line an approval policy needs to draw -- see `Approvals`.
WRITE_TOOLS = frozenset({'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell',
                         'run_python', 'run_shell', 'memory_forget', 'create_skill',
                         'cancel_watch', 'cart_add', 'cart_remove'})

# Every tool failure starts with this. A tool result is just text to the engines underneath
# us -- neither rishi nor fastllm carries an `is_error` flag through to the model -- so the
# flag has to be *in* the text, spelled the same way every time. That is what lets the
# activity feed mark a call as failed, `Agent.problems` collect them, and the model tell
# "the file says X" apart from "I could not read the file".
ERR = 'ERROR: '


def err(what, e=None):
    "One tool failure, spelled the way every other tool spells it."
    return f'{ERR}{what}' + (f': {agent_err(e)}' if e is not None else '')


def failed(result):
    "Whether a tool result is a failure. The one place that knows how a failure is spelled."
    return str(result or '').startswith(ERR)


def clip(s, n=MAX_TOOL_CHARS, more=''):
    """Truncate a tool result to `n` chars, saying how to get the rest.

    Truncation happens here rather than in the context window because a tool result goes
    straight back into the prompt, so the tokens are cheaper to not spend than to spend.
    But a truncated result the model cannot *resume* is a dead end: it will either invent
    the remainder or call the same tool again and get the same first half. So a caller
    with a way to continue passes it as `more`, and it is included in the notice.
    """
    s = str(s)
    if len(s) <= n: return s
    cut = s[:n]
    nl = cut.rfind('\n')                    # never end mid-line: the line would look complete
    if nl > n * 0.6: cut = cut[:nl]
    note = f'[truncated: {len(cut)} of {len(s)} chars shown'
    return cut + f'\n…{note}. {more}]' if more else cut + f'\n…{note}]'


def clip_lines(lines, start=1, n=MAX_TOOL_CHARS, more='', empty='(nothing)'):
    """Render `lines` within the budget, and say which line to resume from.

    The line-oriented half of `clip`. It counts what it dropped rather than describing it
    in characters, because everything that produces lines here -- a file view, a grep, a
    directory -- is resumed by *line or offset*, not by character.

    One line longer than the whole budget is cut by characters, because there is no line to
    resume from: a minified bundle, a one-line JSON blob or a wide CSV row is a single line,
    and returning it whole to keep the result non-empty spent the entire window of a small
    model on one tool call. The notice says characters rather than lines, so the model is not
    invited to resume at a line that would return the same too-long line again.
    """
    lines = list(lines)
    if not lines: return empty
    out, used = [], 0
    for i, line in enumerate(lines):
        line = str(line)
        if used + len(line) + 1 > n:
            if out:
                rest = len(lines) - i
                tail = f'\n…[{rest} more line(s) not shown'
                hint = more.format(next=start + i) if '{next}' in more else more
                return '\n'.join(out) + (f'{tail}. {hint}]' if hint else f'{tail}]')
            keep = max(1, n - 1)
            rest = len(lines) - 1
            more_lines = f', and {rest} more line(s) not shown' if rest else ''
            return line[:keep] + f'\n…[line {start} is {len(line)} chars; {keep} shown{more_lines}]'
        out.append(line); used += len(line) + 1
    return '\n'.join(out)


def _cmds(commands):
    """Parse exhash commands from what a tool call can carry.

    Models emit JSON, exhash wants tuples: `[["12|a1b2|","s","old","new"]]` becomes
    `[("12|a1b2|","s","old","new")]`. Nested command tuples (`g`/`v`) recurse.
    """
    if isinstance(commands, str): commands = json.loads(commands)
    if not isinstance(commands, list): raise ValueError('commands must be a JSON list of command arrays')
    def _t(c):
        if not isinstance(c, (list, tuple)): raise ValueError(f'each command must be an array, got {type(c).__name__}')
        return tuple(_t(x) if isinstance(x, (list, tuple)) else x for x in c)
    return [_t(c) for c in commands]


@functools.lru_cache(maxsize=None)
def _takes_reading(cls):
    "Whether this host's `check` understands the read-only flag. Asked once per class."
    import inspect
    try: return 'reading' in inspect.signature(cls.check).parameters
    except (TypeError, ValueError): return False


def readable(host, path, must_exist=False):
    """Resolve a path a tool is only going to read, through the host's own sandbox.

    Every tool that reads goes through this rather than through `check` directly, so a host
    that allows it can answer for a path outside the open folders while a host written
    before the flag existed sees exactly the call it has always seen.
    """
    if _takes_reading(type(host)): return host.check(path, must_exist=must_exist, reading=True)
    return host.check(path, must_exist=must_exist)


def _declared(host, group):
    "What `host.capabilities` says about `group`, or None when it does not say."
    try: d = host.capabilities or {}
    except Exception: return None
    return bool(d[group]) if group in d else None


def _probe(host, *calls):
    "Whether every one of `calls` is supported. A host says 'no' by raising `NotImplementedError`."
    for f in calls:
        try: f()
        except NotImplementedError: return False
        except Exception: pass
    return True


def _supports(host, name, probe=None):
    """Whether `host` implements `name`, by asking whether it overrode the method.

    Every other capability here is probed by making a harmless call. `run_cmd` has no
    harmless call -- running a command is the side effect -- so it is answered this way
    instead, and `probe` is the *contracted* harmless call a host promises to honour.

    Overriding alone cannot detect a host that implements the method and then refuses
    anyway, which is what `probe` closes: `run_cmd`'s contract says an empty command is a
    no-op returning `(0, '')`, and a host that cannot run commands raises
    `NotImplementedError` from it like any other absent capability.
    """
    own, base = getattr(type(host), name, None), getattr(Host, name, None)
    if own is None or own is base: return False
    if probe is None: return True
    try: probe()
    except NotImplementedError: return False
    except Exception: pass
    return True


def _has(host, group, *calls):
    "Whether `host` supports `group`: its own declaration when it makes one, a harmless call otherwise."
    d = _declared(host, group)
    return _probe(host, *calls) if d is None else d

# %% ../nbs/02_tools.ipynb #367262aa
def code_tools(host, mx=MAX_TOOL_CHARS):
    "Seeing the code: the index, the shapes in it, and the files it covers."

    def search_code(query: str) -> str:
        """Search the codebase and every installed package for `query`.

        Semantic when the code index is built, a literal scan otherwise. Use this before
        writing anything non-trivial: the answer is usually already in the environment.
        """
        hits = host.search(query, limit=MAX_HITS)
        if not hits: return f'no matches ({host.search_note})'
        rows = []
        for h in hits:
            target = ('NOTEBOOK -- use this exact path with notebook_cells, then view_cell/edit_cell'
                      if str(h.path).lower().endswith('.ipynb')
                      else 'FILE -- use this exact path with view_file/edit_file')
            rows.append(f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}\n  {target}')
        return clip(f'[{host.search_note}]\n' + '\n'.join(rows), mx)

    def similar_code(path: str, line: int = 1) -> str:
        "Find code shaped like the function at `path`:`line` -- every place a pattern was already used."
        hits = host.peers(str(readable(host, path)), int(line), limit=MAX_HITS)
        if not hits: return f'nothing similar ({host.search_note})'
        return clip('\n'.join(f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}' for h in hits), mx)

    def outline(path: str) -> str:
        "The defs and classes in one file, with line numbers."
        syms = host.symbols(str(readable(host, path)))
        if not syms: return f'no symbols in {path}'
        return clip('\n'.join(f'{int(getattr(s, "score", 0))*" "}{s.line}: {s.symbol}' for s in syms), mx)

    def list_files(pattern: str = '') -> str:
        "Files in the open folders, optionally filtered by a substring of the path."
        ps = [str(p) for p in host.walk()]
        if pattern: ps = [p for p in ps if pattern.lower() in p.lower()]
        return clip_lines(ps, n=mx, more='narrow `pattern`', empty='no matching files')

    def grep(pattern: str, path_filter: str = '', regex: bool = True, ignore_case: bool = False) -> str:
        """Find every line in the open folders matching `pattern`, exactly.

        The literal counterpart to `search_code`, and not a replacement for it. Use
        `search_code` for "how does this work" -- it is a semantic index and it covers
        installed packages. Use `grep` when you know the string: a symbol you are about to
        rename, an error message, an import, a call site you must not miss. An index answers
        with what is *like* the query; this answers with what *is* the query, which is what
        a rename or an audit needs.

        `path_filter` is a substring of the path (`tests/`, `.py`). Set `regex=False` to
        match `pattern` literally when it contains regex punctuation.
        """
        if not str(pattern or '').strip(): return err('grep needs a pattern')
        flags = re.IGNORECASE if ignore_case else 0
        try: rx = re.compile(pattern if regex else re.escape(pattern), flags)
        except re.error as e: return err('bad pattern', e)
        # Ask the host first. Reading every file through `read` -- and therefore through
        # `check`, and therefore a `resolve` per file -- is what this did for every grep,
        # while the host sitting underneath it had ripgrep the whole time.
        try: fast = host.grep(pattern, path_filter=path_filter, regex=regex,
                              ignore_case=ignore_case, limit=MAX_GREP_HITS)
        except Exception: fast = None
        if fast is not None:
            if not fast: return f'no matches for {pattern!r}'
            capped = len(fast) >= MAX_GREP_HITS
            head = f'{len(fast)}{"+" if capped else ""} match(es)'
            rows = [f'{h.path}:{h.line}: {h.text}' for h in fast]
            return clip_lines([head] + rows, n=mx, more='narrow `pattern` or set `path_filter`')
        pf, hits, scanned, capped = str(path_filter or '').lower(), [], 0, False
        for p in host.walk():
            sp = str(p)
            if pf and pf not in sp.lower(): continue
            try: text = host.read(sp)
            except Exception: continue
            if not text: continue
            scanned += 1
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f'{sp}:{i}: {line.strip()[:200]}')
                    if len(hits) >= MAX_GREP_HITS: capped = True; break
            if capped: break
        if not hits: return f'no matches for {pattern!r} in {scanned} file(s)'
        head = f'{len(hits)}{"+" if capped else ""} match(es) in {scanned} file(s) searched'
        return clip_lines([head] + hits, n=mx, more='narrow `pattern` or set `path_filter`')

    def ls(path: str = '') -> str:
        """List one directory: its subdirectories, then its files with sizes.

        For finding your way around. `list_files` walks everything and `grep` reads
        everything; this just says what is here, which is usually the cheaper question.
        Empty `path` lists each open folder.
        """
        roots = ([readable(host, path)] if str(path or '').strip()
                 else [host.check(r) for r in host.roots])
        out = []
        for d in roots:
            if not d.exists(): out.append(f'{d}: does not exist'); continue
            if d.is_file(): out.append(f'{d}  ({d.stat().st_size} bytes, a file)'); continue
            try: kids = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except Exception as e: out.append(err(f'cannot list {d}', e)); continue
            out.append(f'{d}/')
            for k in kids:
                if k.name.startswith('.') and k.name not in ('.agents', '.leela'): continue
                try: out.append(f'  {k.name}/' if k.is_dir() else f'  {k.name}  {k.stat().st_size}')
                except Exception: out.append(f'  {k.name}')
        return clip_lines(out, n=mx, more='name a subdirectory to list it', empty='(nothing)')

    return [search_code, grep, ls, similar_code, outline, list_files]

# %% ../nbs/02_tools.ipynb #3cd7c09b
def _edits(edits):
    """Parse `replace_text`'s edits from what a tool call can carry.

    Models send this three ways and all three are unambiguous, so all three are accepted:
    a JSON string, a list of `{'oldText','newText'}` dicts, or a list of `[old, new]`
    pairs. Rejecting a shape a model reliably produces buys nothing -- it just costs a
    turn to a message that says "send it the other way".
    """
    if isinstance(edits, str): edits = json.loads(edits)
    if isinstance(edits, dict): edits = [edits]
    if not isinstance(edits, (list, tuple)): raise ValueError('edits must be a JSON array')
    out = []
    for e in edits:
        if isinstance(e, dict):
            if 'oldText' not in e or 'newText' not in e:
                raise ValueError("each edit needs 'oldText' and 'newText'")
            out.append((str(e['oldText']), str(e['newText'])))
        elif isinstance(e, (list, tuple)) and len(e) == 2: out.append((str(e[0]), str(e[1])))
        else: raise ValueError('each edit must be {"oldText":…,"newText":…} or [old, new]')
    return out


def _apply_edits(text, edits):
    """Apply exact-text edits to `text`, or raise saying which one is wrong and why.

    Everything is located against the *original* text first, and only then applied. That
    ordering is the whole design: it is what makes the operation atomic, what lets
    overlap be detected at all, and what means a model whose third edit is stale does not
    have to work out what its first two did to the file.
    """
    spans = []
    for i, (old, new) in enumerate(edits, 1):
        if not old: raise ValueError(f'edit {i}: oldText is empty; use create_file to write a whole file')
        n = text.count(old)
        if n == 0:
            raise ValueError(f'edit {i}: oldText not found. It must match the file exactly, '
                             f'including indentation. Re-read the file and try again')
        if n > 1:
            raise ValueError(f'edit {i}: oldText matches {n} places. Include more surrounding '
                             f'lines so it matches exactly one')
        at = text.index(old)
        spans.append((at, at + len(old), new, i))
    spans.sort()
    for (s1, e1, _, i1), (s2, _, _, i2) in zip(spans, spans[1:]):
        if s2 < e1: raise ValueError(f'edits {i1} and {i2} overlap; merge them into one edit')
    out, at = [], 0
    for s, e, new, _ in spans:
        out.append(text[at:s]); out.append(new); at = e
    out.append(text[at:])
    return ''.join(out)


def _diff(before, after, path='file'):
    "A unified diff, which is what a person approving an edit should be looking at."
    import difflib
    d = difflib.unified_diff(before.splitlines(), after.splitlines(),
                             f'a/{path}', f'b/{path}', lineterm='', n=2)
    return '\n'.join(d)


def file_tools(host, mx=MAX_TOOL_CHARS):
    "Reading and editing files, by exact text or by hash-verified address."

    def view_file(path: str, start: int = 0, end: int = 0) -> str:
        """Read a file as `lineno|hash|content` lines. Optionally limit to lines `start`..`end`.

        Always read this way before editing: `edit_file` addresses lines by the exact
        hashes this returns, so the view is also the address book.
        """
        from exhash import lnhashview_file
        p = readable(host, path)
        if not p.exists(): return err(f'no such file: {p}')
        view = str(lnhashview_file(str(p), start or None, end or None))
        return clip_lines(view.splitlines(), start=(start or 1), n=mx,
                          more='call view_file(path, start={next}) to continue')

    def replace_text(path: str, edits: str) -> str:
        """Edit a file by exact text replacement, and return the diff. Usually the easier editor.

        `edits` is a JSON array of objects, applied together:
          [{"oldText": "def old(a):", "newText": "def new(a, b):"},
           {"oldText": "return a", "newText": "return a + b"}]

        Rules, all of them checked *before* anything is written, so a rejected edit leaves
        the file exactly as it was:

        - Every `oldText` must appear **exactly once** in the file. If it appears twice,
          include more surrounding lines until it is unique -- do not guess which one.
        - Every `oldText` is matched against the file as it is **now**, not against the
          result of the earlier edits in the same call. Overlapping or nested spans are
          refused; merge them into one edit instead.
        - Keep `oldText` as short as it can be while still unique. Do not paste a whole
          function to change one line of it.
        - An empty `oldText` is refused. To create a file use `create_file`; to append,
          include the last existing line in `oldText`.

        This and `edit_file` do the same job by different addresses: `edit_file` names
        lines by hash, which catches a stale read but costs a `view_file` before every
        edit and again after each one. Prefer this for ordinary edits; prefer `edit_file`
        when you must be certain the line you are changing is the line you read.
        """
        p = host.check(path)
        try: items = _edits(edits)
        except Exception as e: return err('could not parse edits', e)
        if not items: return err('no edits given')
        try: before = host.read(str(p))
        except Exception as e: return err(f'could not read {p}', e)
        if before is None: return err(f'no such file: {p}. Use create_file to create it')
        try: after = _apply_edits(before, items)
        except ValueError as e: return err(str(e))
        if after == before: return err('the edits changed nothing; check oldText against a fresh view_file')
        try: host.write(str(p), after)
        except Exception as e: return err('write failed', e)
        return clip(f'replaced {len(items)} block(s) in {p}\n' + _diff(before, after, str(p)), mx)

    def edit_file(path: str, commands: str) -> str:
        """Edit a file with hash-verified exhash commands, and return the diff.

        `commands` is a JSON array of command arrays, each starting with an address taken
        from `view_file`, e.g.
          [["12|a1b2|", "s", "old text", "new text"],
           ["30|9f3c|", "a", "a new line appended after line 30"]]
        Every address's hash is checked immediately before it runs, so an edit built on a
        stale view fails instead of damaging the wrong line. Nothing is written unless
        every command succeeds.
        """
        from exhash import file_exhash
        p = host.check(path)
        try: cmds = _cmds(commands)
        except Exception as e: return err('could not parse commands', e)
        if not cmds: return err('no commands given')
        try: return clip(str(file_exhash(str(p), *cmds)), mx)
        except Exception as e: return err('edit failed', e)

    def create_file(path: str, text: str = '') -> str:
        "Create (or overwrite) a whole file. For changes to an existing file prefer `replace_text`."
        try: return f'wrote {host.write(path, text)}'
        except Exception as e: return err('write failed', e)

    return [view_file, replace_text, edit_file, create_file]

# %% ../nbs/02_tools.ipynb #6c20cd07
def notebook_tools(host, mx=MAX_TOOL_CHARS):
    "Notebooks, addressed by cell id rather than by line."

    def notebook_cells(path: str) -> str:
        "List a notebook's cells: id, type, and first line. Cell ids are what `edit_cell` addresses."
        try: rows = host.nb_cells(str(readable(host, path)))
        except NotImplementedError: raise
        except Exception as e: return err('could not read notebook', e)
        return clip('\n'.join(f'{i}  {t:8} {(s or "").strip().splitlines()[0][:100] if (s or "").strip() else ""}'
                              for i, t, s in rows) or '(empty notebook)')

    def view_cell(path: str, cell_id: str) -> str:
        "Read one notebook cell as `lineno|hash|content` lines, ready to address with `edit_cell`."
        from exhash import lnhashview_cell
        try: return clip(str(lnhashview_cell(str(readable(host, path)), cell_id)))
        except Exception as e: return err('could not read cell', e)

    def edit_cell(path: str, cell_id: str, commands: str) -> str:
        "Edit one notebook cell's source with exhash commands from `view_cell`. Same format as `edit_file`."
        from exhash import cell_exhash
        try: cmds = _cmds(commands)
        except Exception as e: return err('could not parse commands', e)
        try: return clip(str(cell_exhash(str(host.check(path)), cell_id, *cmds)))
        except Exception as e: return err('edit failed', e)

    def add_cell(path: str, source: str, index: int = -1, cell_type: str = 'code') -> str:
        "Insert a new cell into a notebook at `index` (-1 appends). Creates the notebook if needed."
        try: return f'added cell {host.nb_add_cell(str(host.check(path)), source, int(index), cell_type)} to {path}'
        except NotImplementedError: raise
        except Exception as e: return err('could not add cell', e)

    return [notebook_cells, view_cell, edit_cell, add_cell]

# %% ../nbs/02_tools.ipynb #53642256
def web_tools(host, mx=MAX_TOOL_CHARS):
    "The web, for the questions whose answer depends on current documentation."

    def web_search(query: str) -> str:
        "Search the web. Returns titles and urls; follow up with `read_url` on the useful ones."
        docs = host.web_search(query, n=MAX_HITS)
        if not docs: return f'no results ({host.research_note})'
        return clip('\n'.join(f'{d.title}\n  {d.url}' for d in docs))

    def read_url(url: str, remember: bool = True) -> str:
        """Read one web page as markdown; a GitHub file, an arxiv paper or a YouTube
        transcript is read as what it is rather than as the page around it.

        It enters durable research memory by default. Pass `remember=False` for sensitive,
        obviously irrelevant, or exploratory results that should remain ephemeral.
        """
        d = host.read_url(url, remember=remember)
        return clip(d.text if d else f'could not read {url} ({host.research_note})')

    def research(query: str) -> str:
        "Search the web and read the top results into one cited digest. Slower than `web_search`; use for depth."
        return clip(host.research(query) or f'nothing found ({host.research_note})')

    return [web_search, read_url, research]

# %% ../nbs/02_tools.ipynb #e9bae42f
def memory_tools(host, mx=MAX_TOOL_CHARS):
    "Durable pages and research recalled as document sections rather than flat snippets."

    def memory_search(query: str, limit: int = 8) -> str:
        """Search pages remembered from earlier reads and research.

        Returns whole operative sections with breadcrumbs plus related semantic paths. Use
        this before searching the live web when the question may have been researched before.
        """
        try: return clip(json.dumps(host.memory_search(query, int(limit)), default=str), MAX_TOOL_CHARS * 2)
        except Exception as e: return err('memory search failed', e)

    def memory_tree(document: str = '') -> str:
        """Browse remembered document headings without embedding a query.

        `document` may be a title substring or stable document id. Leave it empty to list
        all remembered roots, then call again with the relevant document.
        """
        try: return clip(json.dumps(host.memory_tree(document), default=str), MAX_TOOL_CHARS * 2)
        except Exception as e: return err('memory tree failed', e)

    def memory_read(node_id: str) -> str:
        "Read one whole remembered section by the node id returned by memory_search/tree."
        try: return clip(json.dumps(host.memory_read(node_id), default=str), MAX_TOOL_CHARS * 3)
        except Exception as e: return err('memory read failed', e)

    def memory_topics(limit: int = 12) -> str:
        "Map remembered material into labelled semantic clusters and representative members."
        try: return clip(json.dumps(host.memory_topics(int(limit)), default=str), MAX_TOOL_CHARS * 2)
        except Exception as e: return err('memory topics failed', e)

    def ask_memory(question: str, document: str = '', instruction: str = '') -> str:
        """Ask remembered research a question and get a short cited answer, not the sections.

        Prefer this to `memory_search` when you want an answer rather than material: the search
        returns whole sections into your context and this returns a paragraph, which is the same
        trade `delegate_search` makes. `document` narrows it to one remembered document by title
        or id.

        Some of what the vault holds is private -- a statement, a medical letter, an exported
        chat. Those are answered by a model on this machine that is instructed not to repeat any
        personal detail to you, so what you get back is shape and quantity: how many, what kind,
        which period, whether two things agree. It will tell you what it is holding and what
        instruction would let it answer usefully. Send that back as `instruction` and it gets
        another turn on the same material.

        Do not ask it for the details it withheld, or ask it to relay them "for the user". It
        will refuse, and the refusal is the point rather than an obstacle.
        """
        try: r = host.ask(question, ref=document or None, instruction=instruction)
        except NotImplementedError: raise
        except Exception as e: return err('could not ask memory', e)
        rows = [str(r.get('answer') or '(no answer)')]
        if (p := r.get('pii')) and p.get('has_pii'):
            rows.append(f"\n[answered on a local model; it holds back "
                        f"{', '.join(sorted(p.get('identifying') or {}))}. Reply with `instruction=` "
                        f"to say what you need -- a count, a total, a comparison, a yes or no.]")
        if (c := r.get('cited')):
            rows.append('\n' + '\n'.join(f"[{x['n']}] {x['breadcrumb']}  ({x['node_id']})" for x in c))
        return clip('\n'.join(rows), MAX_TOOL_CHARS * 2)

    def memory_forget(doc_id: str) -> str:
        """Purge one bad, sensitive, stale or irrelevant remembered document by id.

        This removes its tree, chunks and ANN entries. Use only when the user requests it;
        do not silently curate their memory.
        """
        try: return 'forgot document' if host.memory_forget(doc_id) else 'document was not forgotten'
        except Exception as e: return err('memory purge failed', e)

    tools = [memory_search, memory_tree, memory_read, memory_topics, memory_forget]
    # `ask` is a model call rather than a lookup, and a host can perfectly well have a store of
    # remembered research and nothing to ask it with -- so this one is not part of the group.
    if _supports(host, 'ask'): tools.insert(4, ask_memory)
    return tools

# %% ../nbs/02_tools.ipynb #apitools01
def api_tools(host, mx=MAX_TOOL_CHARS):
    """Read an API specification, browse what it declares, and call one operation.

    The signature `api_ops` reports is the one `api_call` accepts, because both are built from
    the same `OpSpec`. A model that read the list therefore cannot invent a parameter the
    service does not take, which is the failure mode of asking it to compose a request by hand.
    """

    def api_load(src: str, name: str = '') -> str:
        """Load an OpenAPI or discovery document from a url or a path.

        Do this before `api_ops` or `api_call`. `src` is often `<host>/openapi.json`. Returns
        the operation count and the groups, which is what to narrow by next.
        """
        try: return clip(json.dumps(host.api_load(src, name), default=str), mx)
        except Exception as e: return err('could not load the spec', e)

    def api_ops(group: str = '', name: str = '', match: str = '') -> str:
        """List the operations a loaded spec declares, with their signatures.

        Narrow with `group` or `match` first: a real API has hundreds of operations, and
        reading all of them is not how you find the one you want.
        """
        try: return clip(json.dumps(host.api_ops(group, name, match), default=str), mx)
        except Exception as e: return err('could not read the operations', e)

    def api_call(operation: str, name: str = '', params: dict = None) -> str:
        """Call one operation, passing `params` under the names `api_ops` reported.

        A parameter the operation does not declare is an error rather than an extra query
        field, which is what makes a wrong call fail loudly instead of quietly.
        """
        try: return clip(json.dumps(host.api_call(operation, name, **(params or {})), default=str), mx)
        except Exception as e: return err(f'{operation} failed', e)

    return [api_load, api_ops, api_call]


# %% ../nbs/02_tools.ipynb #f91b907d
def watch_tools(host, mx=MAX_TOOL_CHARS):
    "Standing interests: what to put back on the desk later, and what has come due now."

    def remember(text: str, title: str = '', tags: str = '') -> str:
        """Write a conclusion into durable memory so a later session finds it.

        For what you worked out, not for what you read -- `read_url` already files pages.
        `tags` is a comma-separated list.
        """
        try:
            d = host.remember(text, title=title or None,
                              tags=[t.strip() for t in tags.split(',') if t.strip()])
            return f"remembered {d.get('title')!r} as {d.get('doc_id')}"
        except Exception as e: return err('could not remember', e)

    def set_reminder(text: str, every: str = '1w', note: str = '') -> str:
        """Come back to `text` every `every` ('30m', '6h', '1d', '1w').

        The reminder files itself into memory when it comes due, so it surfaces in
        `memory_search` and in `poll_watches` rather than needing a notification channel.
        """
        try:
            w = host.watch(text, action='remind', every=every, note=note or None)
            return f"reminder {w['id']} set, every {every}"
        except Exception as e: return err('could not set reminder', e)

    def watch_url(url: str, every: str = '1d', note: str = '') -> str:
        "Re-read `url` every `every` and file each version in memory, so changes are visible over time."
        try:
            w = host.watch(url, action='url', every=every, note=note or None)
            return f"watching {url} as {w['id']}, every {every}"
        except Exception as e: return err('could not watch', e)

    def list_watches(due_only: bool = False) -> str:
        "Every standing watch and reminder, soonest first. `due_only` shows just what has come due."
        try:
            ws = host.watches(due_only=bool(due_only))
            if not ws: return 'nothing is being watched'
            return clip('\n'.join(
                f"{w['id']}  {w['action']:8} every {int(w['every'])}s  runs={w['runs']}"
                f"  {w.get('last_status') or 'never run'}  {str(w['target'])[:80]}" for w in ws))
        except Exception as e: return err('could not list watches', e)

    def cancel_watch(watch_id: str) -> str:
        "Delete one watch by id. Only when the user asks; do not silently curate their reminders."
        try:
            host.unwatch(watch_id)
            return f'cancelled {watch_id}'
        except Exception as e: return err('could not cancel', e)

    def poll_watches() -> str:
        """Run every watch that has come due, and report what fired.

        Call this when the user asks what is outstanding, or at the start of a session.
        Anything that fired is now in memory: follow up with `memory_search`.
        """
        try:
            r = host.poll()
            if not r.get('ran'): return f"nothing due ({r.get('checked', 0)} watched)"
            lines = [f"{x['status']:7} {x['action']:8} {str(x['target'])[:90]}" for x in r['results']]
            return clip(f"{r['ran']} of {r['checked']} fired\n" + '\n'.join(lines))
        except Exception as e: return err('poll failed', e)

    return [remember, set_reminder, watch_url, list_watches, cancel_watch, poll_watches]

# %% ../nbs/02_tools.ipynb #b453bc91
def session_tools(host, mx=MAX_TOOL_CHARS):
    "The live kernel the user is working in, and the terminal they are looking at."

    def list_vars() -> str:
        "List the variables visible in the user's live session: name, type, and a short value."
        return clip(host.list_vars() or '(empty session)')

    def run_python(code: str) -> str:
        """Run Python in the user's live kernel namespace.

        Read any variable freely; bind results to NEW names so they survive to the next
        call. Mutating or deleting the user's variables is refused -- rebind instead
        (`df2 = df.drop(...)`). Call `list_vars` first if you do not know what is there.
        """
        try: return clip(host.run_python(code))
        except NotImplementedError: raise
        except Exception as e: return err('run failed', e)

    def inspect_python(code: str, scope: str = 'isolated') -> str:
        """Look at the user's live variables by running Python that cannot change them.

        Two scopes. Both leave the user's variables exactly as they were; they differ in
        how much Python you get, so pick by what the question needs:

        - `scope='isolated'` (default) runs in an allowlist sandbox on a copy. Attribute
          reads and builtins work -- `df.shape`, `len(df)`, `type(x).__name__` -- and most
          library method calls are refused. Costs nothing to be wrong about.
        - `scope='overlay'` runs the real interpreter against the real namespace. Library
          calls work: `list(df.columns)`, `df.head(3).to_dict()`, `model.summary()`. Names
          you bind persist into your own layer for later calls. You still cannot delete,
          rebind or mutate anything the user made -- that is refused, with an explanation.

        Start isolated; move to overlay when the sandbox refuses something you need. Neither
        needs approval, and both run while one of the user's cells is still going. For work
        that must land in the *user's* namespace, use `run_python` instead.
        """
        try: return clip(host.inspect_python(code, scope=scope))
        except NotImplementedError: raise
        except Exception as e: return err('inspection failed', e)

    def read_terminal(lines: int = 200) -> str:
        """Read what the IDE's terminal has printed -- a failing build, a stack trace, a test run.

        This is *read only*: it shows what the user ran, and cannot run anything. Use it
        when they mention an error they are looking at rather than asking them to paste it.
        """
        return clip(host.terminal_text(int(lines)) or 'the terminal has printed nothing yet')

    # No `scale_numeric`. It was a pandas min-max scaler, spelled out as a tool, in the tool
    # list of a general coding harness -- one library's one transformation, permanently in
    # every model's context whatever the project is written in. `coding_patterns` says not to
    # do this, and `run_python` composes it in a line when somebody actually wants it.
    return [list_vars, run_python, inspect_python, read_terminal]

# %% ../nbs/02_tools.ipynb #sh311770
def shell_tools(host, mx=MAX_TOOL_CHARS):
    "Running a command, which is the only way to find out whether the work is done."

    def run_shell(command: str, cwd: str = '', timeout: int = 120) -> str:
        """Run one shell command in the project and return its exit code and output.

        This is how you check your work, and you are expected to use it: after an edit, run
        the tests; after a change to a signature, run the type checker or the linter the
        project already uses; before saying something passes, make it pass here. A claim
        with no command behind it is a guess, and will be read as one.

        - stdout and stderr come back interleaved, as a person would see them, with the
          exit code on the first line. A non-zero exit is a *result*: read the output and
          fix the cause, do not run it again unchanged.
        - `cwd` defaults to the first open folder and must stay inside the open folders.
        - `timeout` is in seconds; the command is killed when it expires. Do not start
          servers, watchers, REPLs, or anything else that does not exit on its own.
        - Use the project's own commands -- the ones in its README, `pyproject.toml`, or
          `Makefile` -- rather than a global tool that may not be what it uses.
        - This may be put to the user for approval, so send one purposeful command rather
          than a chain of exploratory ones.
        """
        cmd = str(command or '').strip()
        if not cmd: return err('no command given')
        try: code, out = host.run_cmd(cmd, cwd=(str(cwd).strip() or None), timeout=int(timeout))
        except NotImplementedError: raise
        except Exception as e: return err('command could not be run', e)
        head = f'exit {code}' + ('' if code == 0 else '  (command FAILED)')
        body = clip((out or '').rstrip() or '(no output)', mx - 200,
                    more='re-run narrowing the command (a single test, `| tail -50`) rather than repeating it')
        return f'{head}\n{body}' if code == 0 else f'{ERR}{head}\n{body}'

    return [run_shell]

# %% ../nbs/02_tools.ipynb #cbb32215
def skill_tools(host, get_skills, mx=MAX_TOOL_CHARS):
    "Reading discovered skills and creating project-local Agent Skills."

    def read_skill(name: str) -> str:
        """Read one skill in full: how to use a tool or a library that is already installed here.

        The skill list in your briefing gives names and one-line descriptions. Read the
        matching one *before* doing the work it describes, not after it has gone wrong.
        """
        ss = get_skills()
        s = find(ss, name)
        if s is None:
            return f'no skill matching {name!r}. Available: ' + ', '.join(x.name for x in ss)
        return clip(f'<skill name="{s.name}" from="{s.where}">\n{s.text()}\n</skill>', MAX_TOOL_CHARS * 3)

    def create_skill(name: str, description: str, instructions: str) -> str:
        """Create a reusable project skill at `.agents/skills/NAME/SKILL.md`.

        Use this only when the user asks to preserve repeatable project know-how as a
        skill, not for ordinary task notes. `name` must be lowercase kebab-case;
        `description` says when it applies; `instructions` is the complete Markdown body.
        Existing skills are never overwritten. Run `/reload` after creation to make the
        current agent advertise it immediately.
        """
        from pathlib import Path
        name = str(name or '').strip()
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            return 'skill name must be lowercase kebab-case (for example, notebook-tests)'
        if not str(description or '').strip(): return 'skill description is required'
        if not str(instructions or '').strip(): return 'skill instructions are required'
        roots = list(host.roots or ())
        if not roots: return 'open a project folder before creating a skill'
        target = Path(host.check(Path(roots[0])/'.agents'/'skills'/name/'SKILL.md'))
        exists = target.exists()
        if not exists:
            try: exists = host.read(str(target)) is not None
            except Exception: pass
        if exists: return f'refusing to overwrite existing skill: {target}'
        title = json.dumps(name, ensure_ascii=False)
        desc = json.dumps(' '.join(str(description).split()), ensure_ascii=False)
        text = f'---\nname: {title}\ndescription: {desc}\n---\n\n{str(instructions).strip()}\n'
        try: host.write(str(target), text)
        except Exception as e: return err('could not create skill', e)
        return f'created {target}; run /reload to load it into the current agent'

    return [read_skill, create_skill]

# %% ../nbs/02_tools.ipynb #ddf75013
def tools_for(host, get_skills=None, extra=(), mx=MAX_TOOL_CHARS, drop=()):
    """Every tool this host can actually support, plus whatever extensions registered.

    Each group is dropped whole if the host does not implement it. Whole groups rather than
    individual tools because the groups are the real units of capability: a host with no
    notebook representation cannot support any of the four notebook tools, and one with no
    kernel cannot support any of the session ones.

    A group is answered by `Host.capabilities` when the host declares it, and by a harmless
    call otherwise. The declaration exists because the probe is not always harmless: it is
    the *first* thing to touch the host, so a capability whose answer sits behind a model
    load is one the probe waits through -- which is how a vault opened in the background to
    keep the tool list fast came to be the reason the tool list was slow.

    `mx` is what one tool result may spend. It belongs here rather than in each tool
    because it is a property of the *model* the results are going to, not of the tool: the
    same `view_file` that should return 300 lines to a frontier model has to return 60 to
    an on-device one, and getting that wrong is not a formatting problem -- a turn whose
    tool results overflow a 16k window fails outright.

    `drop` withholds groups the host *does* support, which is the other half of the same
    arithmetic: on a small window the schemas themselves are the cost, and a group whose
    results cannot fit is one whose declaration should not be paid for. `core.budget_for`
    decides which, so the decision stays beside the routing table. A dropped group is never
    silently unavailable -- `Agent.budget` says so, and the briefing describes only the tools
    that were actually built.
    """
    drop = set(drop or ())
    tools = []
    if 'code' not in drop: tools += code_tools(host, mx)
    if 'file' not in drop: tools += file_tools(host, mx)
    if 'notebook' not in drop and _has(host, 'notebook', lambda: host.nb_cells('.')): tools += notebook_tools(host, mx)
    if 'web' not in drop and _has(host, 'web', lambda: host.web_search('', n=1)): tools += web_tools(host, mx)
    if 'memory' not in drop and _has(host, 'memory', lambda: host.memory_tree('')): tools += memory_tools(host, mx)
    if 'watch' not in drop and _has(host, 'watch', lambda: host.watches()): tools += watch_tools(host, mx)
    # Declared, never probed: the probe would be `api_ops`, and a host with no spec loaded
    # yet answers that by raising -- which is a missing spec, not a missing capability.
    if 'api' not in drop and _declared(host, 'api'): tools += api_tools(host, mx)
    if 'session' not in drop and _has(host, 'session', lambda: host.list_vars(), lambda: host.terminal_text(1)): tools += session_tools(host, mx)
    # `run_cmd` is the one capability with no harmless probe, so it is answered by asking
    # whether the host overrode the method rather than by running something.
    shell = _declared(host, 'shell')
    if 'shell' not in drop and (_supports(host, 'run_cmd', lambda: host.run_cmd('')) if shell is None else shell):
        tools += shell_tools(host, mx)
    if get_skills is not None and 'skill' not in drop: tools += skill_tools(host, get_skills, mx)
    tools += list(extra or ())
    return tools

# %% ../nbs/02_tools.ipynb #e3b29ea1
SUB_MAX_STEPS = 12

SUB_SP = """You are a research sub-agent inside a Python IDE. Another agent has delegated one \
question to you because answering it takes many tool calls and the answer is short.

- Answer exactly the question asked. Nothing else.
- Use your tools as much as you need; nobody is paying attention to how many calls it takes.
- Report what you found, with file paths and line numbers, not what you infer or expect.
- If the answer is that there is nothing, say so plainly. A confident wrong answer is far \
worse than "no matches, and here is what I searched for".
- You cannot edit anything. If the answer implies a change, describe the change and stop.
- `inspect_python` answers questions about the user's live variables without changing them. \
Its default scope is a sandbox that refuses most library calls; pass `scope='overlay'` to \
get the real interpreter. Use it rather than guessing at what is in memory."""


# A sub-agent does not get to spawn sub-agents. Not a safety rule so much as an economic
# one: recursion here is a fan-out tree whose width nobody chose, and the second level
# never has enough context to ask a good question anyway.
NO_SUB = frozenset({'delegate_search', 'delegate_parallel'})

# %% ../nbs/02_tools.ipynb #8ca3589d
def read_only(tools, max_calls=None):
    "The read-only tools a sub-agent may have, optionally behind a hard per-task call budget."
    allowed = [t for t in tools if getattr(t, '__name__', '') not in (WRITE_TOOLS | NO_SUB)]
    if max_calls is None: return allowed
    state, lock = {'n': 0}, threading.Lock()

    def guarded(f):
        @functools.wraps(f)
        def call(*args, **kw):
            with lock:
                state['n'] += 1
                over = state['n'] > max_calls
            if over:
                return ('Sub-agent tool budget exhausted. Stop calling tools and return the '
                        'best evidence-backed answer now.')
            return f(*args, **kw)
        return call
    return [guarded(t) for t in allowed]

# %% ../nbs/02_tools.ipynb #0818dbdb
def sub_sp(sp=SUB_SP, skills=()):
    """A sub-agent's briefing: its standing instructions, then the skills its task named.

    Inlining a skill body is wrong for a turn and right here, and the difference is knowing the
    task. A conversation could need any skill, so the turn gets an index and pays for a body
    only when it asks; a sub-agent has exactly one job, named by the caller who *does* hold the
    index, so the body it needs can be there from the first step. On the small local model
    sub-agents route to by default, that is the difference between spending one of a dozen steps
    on `read_skill` and spending none.

    Discovery stays with the caller on purpose. Handing the sub-agent the whole index as well
    would put the choice back on the model with the fewest tokens to make it with.
    """
    if not skills: return sp
    return sp + '\n\n' + '\n\n'.join(f'## {s.name}\n\n{s.text()}' for s in skills)


def delegate(backend, question, tools=(), sp=SUB_SP, max_steps=SUB_MAX_STEPS, skills=()):
    """Ask `question` in a throwaway conversation on `backend`'s engine. Returns the answer text.

    The conversation is closed in a `finally` because the whole benefit is that it does not
    outlive the question -- a sub-agent whose context leaks back into the session is just a
    slower way of doing the work inline.
    """
    sub = None
    try:
        # Native local engines own their internal tool loop, so the tool wrappers are the
        # backend-independent hard stop. Allow several parallel calls per logical round.
        sub = backend.spawn(sp=sub_sp(sp, skills), tools=read_only(tools, max_calls=max_steps * 4))
        if hasattr(sub, 'max_steps'): sub.max_steps = max_steps
        return sub.send(question)
    except Exception as e:
        return err('delegation failed', e)
    finally:
        if sub is not None:
            try: sub.close()
            except Exception: pass

# %% ../nbs/02_tools.ipynb #fe517832
def delegate_many(backend, questions, tools=(), sp=SUB_SP, max_steps=SUB_MAX_STEPS, n_workers=4, skills=()):
    """Ask several questions at once. Returns answers in the order the questions were given.

    Whether this is genuinely parallel depends on what is underneath, and it is worth being
    exact rather than optimistic:

    - **Generation** overlaps on a cloud backend, where each sub-agent is its own HTTP
      request. On a local engine it does not -- litert holds one conversation at a time --
      so local fan-out is run one after another rather than racing for the same engine and
      finding out what happens.
    - **Tool work** overlaps either way, and is usually the bulk of it: three sub-agents
      each doing six searches is eighteen searches, and they do not wait for each other.
      Under a concurrent kernel (`Host.kernel_kind == 'ipymini'`) that includes
      `inspect_python`, which is the case that used to be hopeless -- an inspection queued
      behind the user's running cell, and then behind the other two sub-agents' inspections.

    The point of the whole thing is context, not speed. Three questions answered in
    parallel cost the caller three short answers instead of sixty tool results.
    """
    qs = list(questions)
    if not qs: return []
    if len(qs) == 1 or getattr(backend.spec, 'local', False) or n_workers < 2:
        return [delegate(backend, q, tools, sp, max_steps, skills) for q in qs]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(min(n_workers, len(qs))) as ex:
        return list(ex.map(lambda q: delegate(backend, q, tools, sp, max_steps, skills), qs))

# %% ../nbs/02_tools.ipynb #906e7f69
def named_skills(get_skills, names):
    """The skills a delegated task named, and a note about any name that matched nothing.

    A name that matched nothing is reported rather than dropped. A sub-agent quietly briefed
    without the skill its caller asked for answers from general knowledge and sounds exactly as
    confident as one that had it.
    """
    if not names or get_skills is None: return [], ''
    every = list(get_skills() or [])
    got, missing = [], []
    for n in [x for x in str(names).replace(',', ' ').split() if x]:
        s = find(every, n)
        got.append(s) if s is not None else missing.append(n)
    if not missing: return got, ''
    return got, (f"\n\n[no skill named {', '.join(missing)}; this repository has "
                 f"{', '.join(s.name for s in every) or 'none'}]")


def subagent_tools(get_backend, get_tools, get_skills=None):
    """The `delegate` tool, bound to whatever backend routing says sub-agents run on.

    Every argument is a callable so a model switch mid-session is picked up: the tool the
    model is holding must not be pinned to the backend that happened to be current when
    the tool list was built. `get_tools` is asked for the sub-agent model's tool list rather
    than the turn model's, which is the same arithmetic `core.budget_for` does for a turn --
    sub-agents route to a small local model by default, and handing it a frontier model's
    schemas at a frontier model's clip is the overflow that budget exists to prevent.
    """

    def delegate_search(question: str, skills: str = '') -> str:
        """Hand a broad search question to a sub-agent and get back only its conclusion.

        Use this when answering would take many `search_code` / `view_file` / `read_url` /
        `inspect_python` calls whose results you do not need to keep -- "where else do we
        do X", "which files import Y", "what shape is everything in this namespace". The
        sub-agent has your read-only tools and none of your write tools, and its working is
        discarded, so the cost to your context is one question and one answer.

        `skills` names skills from your skill index, comma separated, whose text the sub-agent
        should start with: name the one or two its task actually needs. You hold the index and
        it does not, so this is the only way it gets a skill without spending a step reading
        one. Leave it empty when the task needs no particular skill.

        Ask one self-contained question. The sub-agent cannot see this conversation.
        """
        b = get_backend()
        if b is None: return 'no model is available to delegate to'
        sk, note = named_skills(get_skills, skills)
        return clip(delegate(b, question, get_tools(), skills=sk), MAX_TOOL_CHARS) + note

    def delegate_parallel(questions: str, skills: str = '') -> str:
        """Hand several independent questions to sub-agents at once, and get back every answer.

        `questions` is a JSON array of strings, e.g.
          ["which files import fastllm?", "where is compaction triggered?", "what is df's shape?"]

        Use it when you have two or more questions that do not depend on each other. They
        run concurrently, each in its own throwaway conversation with your read-only tools,
        so three questions cost you three short answers rather than the sixty tool results
        it would take to answer them yourself.

        `skills` names skills from your skill index, comma separated, given to every one of
        them. Use it when the questions share a subject; when they do not, ask them in separate
        `delegate_search` calls so each gets only what its own task needs.

        Every question must be self-contained: a sub-agent cannot see this conversation or
        the other questions.
        """
        b = get_backend()
        if b is None: return 'no model is available to delegate to'
        try:
            qs = json.loads(questions) if isinstance(questions, str) else list(questions)
            if not isinstance(qs, list) or not all(isinstance(q, str) for q in qs):
                raise ValueError('expected a JSON array of strings')
        except Exception as e:
            return err('could not parse questions', e)
        if not qs: return 'no questions given'
        sk, note = named_skills(get_skills, skills)
        answers = delegate_many(b, qs, get_tools(), skills=sk)
        return clip('\n\n'.join(f'### {q}\n{a}' for q, a in zip(qs, answers)), MAX_TOOL_CHARS * 2) + note

    return [delegate_search, delegate_parallel]
