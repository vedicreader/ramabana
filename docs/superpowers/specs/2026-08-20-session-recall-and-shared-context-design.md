# Session recall, context collage, and two agents in one namespace

Date: 2026-08-20
Status: draft, for review

## What this is

Three changes across ramabana, leela and dhrishti, sharing one subject: what an agent may remember from work already done, and what happens when a second agent is in the room.

Most of the machinery exists. Both session stores are already written and already served. Per-cell context pruning is already a user-facing toggle that the compactor already honours. Attaching grounded text to a turn is already a typed reference with three kinds. What is missing is search over the stores, a place to put what search returns, and a deliberate answer to two agents sharing a namespace. That last one is not new work in the usual sense. It is the accidental behaviour today, and it is unsafe.

## What is already there

### Two session stores, neither searchable

Ramabana persists one JSON object per turn to `{cfg}/{history_name}-history.jsonl`, carrying `session`, `turn_id`, `branch_id`, `model`, `prompt`, `reply`, `error`, `plan`, `usage`, and `activity` (the clipped tool rows). `Agent.sessions()` groups them for a picker. `Agent.resume_session()` replays one whole session into the model's context as alternating user and assistant messages. Leela runs two of these per workspace, `agent-history.jsonl` for the pane and `inline-history.jsonl` for prompt cells.

Dhrishti writes an execution transcript per agent session to `AGENT_SESSION_DIR/agent_<stamp>.ipynb`. `AgentSession._log` appends every attempted cell, outcome first, tagged `# blocked:`, `# error:` or `# scope: isolated`. `conversation_logger` interleaves `**user**` and `**assistant**` markdown between the code cells. `list_agent_sessions` and `read_agent_session` read them back, and `/agent/api/sessions` and `/agent/api/transcript` serve them.

Leela already joins the two. `/agent/history` calls `_history_sessions(turns, execution)`, which groups ramabana turns by `session` id and merges dhrishti's code-cell count onto the matching row. The join key exists and works.

Neither store can be searched. Resume is the only way back into one, and it is all or nothing.

### Pruning, already a toggle the compactor obeys

`Cell.context_mode` is `auto`, `keep` or `discard`, stored under `metadata.leela.context`, cycled by a button in the cell gutter. `Notebook.context(i)` emits each cell above the prompt as `<cell id= type= compact=>` with `<source>`, `<output>` and `<answer>` children, and under a character budget it keeps every `keep` cell and tail-clips the rest.

Ramabana reads the same markup. `compact_notebook_context(prompt, fits)` finds the `<notebook>` block, removes `discard` cells first and `auto` cells second, one at a time, until the prompt fits, and leaves a `<context-compacted omitted= discard= auto= />` marker saying what went. A `keep` cell is never removed.

So user pruning and automatic pruning already speak one protocol, over one markup, at cell granularity. Anything that wants both for free should arrive as cells carrying `compact=`.

### Attachment, already typed

`Workspace._attachment_context` takes a list of refs and returns grounded text plus multimodal parts. A ref is a path, or a dict with `kind` of `selection` or `vault`. Each becomes an element: `<attached-file path=>`, `<attached-folder path= files=>`, `<attached-selection path= lines=>`, `<attached-document vault= shelf= title= source=>`. The prompt bar has an `@` completer for files and vault documents, and chips in the composer.

### The prompt cell, already grounded by the notebook above it

`/nb/ask/stream` reaches `Workspace.ask_cell_stream(nb, i)`, which calls `_agent_context(nb, i, ...)` for `nb.context(i)` and hands it to `inline_ai.stream_with(source, context=..., context_path=nb.path)`. `Agent.compose` wraps it as `<notebook path=>`. The inline agent is a separate `Assistant` with its own durable history. `Notebook.prompt_start` returns 0, meaning a prompt cell reads from the top of the document rather than from backend chat history, which is what makes the notebook the context rather than a transcript.

### Two agents in one namespace, already true and already unsafe

`dhrishti.serving._agent` is a module-level singleton. `agent_session()` returns it, creating one `AgentSession` on first call. Every client of one dhrishti server therefore shares one overlay layer, one merged namespace and one transcript notebook.

That means variable sharing between two agents already works, by accident, with three defects:

- No demarcation. Nothing in the transcript says which agent wrote a cell, and nothing in the namespace says which agent bound a name.
- No collision handling. Two agents binding `df2` silently overwrite each other, and `_sync_out` copies whichever ran last back into the shared layer.
- No serialisation. `AgentSession.run` does `_sync_in`, `exec`, `_sync_out` with no lock. `log_run` reads the whole notebook, appends a cell, and writes the whole file back, inside a bare `except: pass`. Two agents appending at once lose cells and never report it.

The owner protection itself holds under concurrency, because `owner_names()` is recomputed per call and the AST policy refuses before anything executes. What breaks is the agents' own state.

## What is missing

1. Search over the two session stores, at a granularity smaller than a session.
2. Somewhere to put what search returns, that the user and the agent can both prune.
3. A way to seed a prompt cell with that material before the first turn.
4. Per-agent identity, explicit publication between agents, and a lock, in dhrishti.

## Recall, in ramabana

### The Host contract

Three methods on `Host`, alongside the memory group they are modelled on, plus a `recall` capability key:

    recall_search(query, limit=8, scope='', outcome='')   # fragments, ranked
    recall_outline(session='')                            # sessions, or one session's fragments
    recall_read(ref)                                      # one fragment in full

`scope` narrows to a surface (`agent`, `inline`) or a session id. `outcome` keeps only fragments whose turn succeeded, or only those that failed. Every method may raise, and an absent one raises `NotImplementedError`, which is how `tools_for` drops the group.

### The fragment

Retrieval below session granularity needs an addressable unit. A fragment is one of four things, each with a stable `ref` string:

| kind | ref | source |
|---|---|---|
| `prompt` | `{sid}/{turn_id}#prompt` | the user's text for one turn |
| `reply` | `{sid}/{turn_id}#reply` | the assistant's text for one turn |
| `act` | `{sid}/{turn_id}#act:{n}` | one activity row, tool, args and clipped result |
| `cell` | `{sid}/cell:{n}` | one dhrishti transcript cell |

A fragment carries `ref`, `kind`, `session`, `at`, `model`, `text`, and `ok`. `ok` is false for a turn with a non-empty `error`, an activity row with `ok: false`, or a transcript cell whose source begins `# blocked:` or `# error:`. Nothing is dropped for being a failure. A failed attempt is often the most useful thing in the store, and the caller decides.

### `SessionIndex`

A new notebook `16_recall.ipynb` exports `ramabana/recall.py` holding `SessionIndex`, which reads `{cfg}/*-history.jsonl` and, when given a transcript directory, the `agent_*.ipynb` files beside them. It has one job: turn both stores into fragments and rank them.

Ranking has two backends. Where a `Vault` is present, fragments go into a `sessions` shelf and search runs through `Vault.federate`, joining the vault leg with the code legs the way `VaultHost.search` already does. Where there is no vault, `SessionIndex` scans linearly and scores by token overlap. The scan is honest about its cost: a 5,000-turn log is a few megabytes of JSON and a scan is tens of milliseconds, and past that the vault is the answer rather than a better scan.

`VaultHost` implements the three methods against a `SessionIndex` built on its own `cfg`. `LocalHost` implements them against the scan. `WorkspaceHost` in leela overrides them to add dhrishti's transcripts, since the workspace is what knows where the kernel is logging.

### The feedback risk, and what to do about it

Searching agent sessions means searching the agent's own output, and a wrong answer retrieved and re-grounded becomes a wrong answer with a citation. Two defences, both cheap because the data is already recorded.

Rank demotes failures. A fragment whose turn carries an `error`, or whose activity row is `ok: false`, is scored below an equal match that succeeded. It still appears, and `outcome='failed'` asks for it directly.

The tool descriptions say what the material is. Recalled text is what an agent said, and it is evidence about what was tried rather than a statement of fact about the code. The briefing rule already in `RULES` covers the general case ("Never claim a file changed... unless a tool result in this conversation says so"), and the recall tools restate it for their own results.

### `recall_tools`

Three tools, mirroring the memory group's browse, search and read triad:

- `search_sessions(query, limit=8, scope='', outcome='')`. Ranked fragments as JSON rows with `ref`, `session`, `at`, `kind`, `ok` and a snippet.
- `session_outline(session='')`. Sessions newest first with turn counts, first prompt and models, or one session's fragments as a list of one-liners. This is the cheap browse, and it embeds no query.
- `read_session_fragment(ref)`. One fragment in full.

`tools_for` gains `if 'recall' not in drop and _has(host, 'recall', lambda: host.recall_outline('')): tools += recall_tools(host, mx)`, and `recall` joins `FRUGAL_DROP` next to `memory` and `web`, because a small-window model cannot afford another retrieval surface.

Two rules join `RULES`, both tagged `search_sessions` so they are filtered out when the tool is absent:

- Search prior sessions before repeating work that sounds like work already done, and prefer a successful prior attempt over a failed one unless the failure is what you are asking about.
- Recalled text is what an agent said in an earlier session. Treat it as evidence about what was tried, and verify anything you are about to act on against the code as it stands now.

## The collage, in leela

### It is a notebook

A collage is an ordinary `.ipynb` under `.leela/collages/<name>.ipynb`, opened in an ordinary editor tab. Every cell carries `metadata.leela.origin` naming the fragment it came from, alongside the `context` mode it already carries.

Making it a notebook rather than a new object is most of the value here. Cell editing, the context toggle, split and merge, save, git, the outline, and the `@` completer all work on it the day it exists. Nothing new renders it. The user prunes it with the button that is already in the gutter, and a user who wants to rewrite a recalled cell into something shorter uses the editor.

`Cell` gains one field, `origin: str = ''`, written into `metadata.leela.origin` by `nbcell` and read by `from_nb`. `_context_cell` emits it as an attribute, giving `<cell id= type= compact= origin=>`, which is how a model cites what it is quoting.

### Building one

`/recall/search` runs `ws.ai.host.recall_search` and returns rows for a results panel beside the vault workbench, which already has the row-with-attach-button pattern. Each row has three actions: attach to the next turn, add to a collage, and open the whole session.

`/recall/collage` takes a list of refs and a target name, calls `recall_read` on each, and appends one cell per fragment. A `prompt` or `reply` fragment becomes a markdown cell. An `act` or `cell` fragment becomes a code cell where the source is code and a markdown cell otherwise. Default `context_mode` is `keep` for anything the user picked by hand and `auto` for anything an agent added, because a user who clicked a row meant it.

### Attaching one

`_attachment_context` gains two ref kinds:

    {'kind': 'session', 'ref': '<fragment ref>'}
    {'kind': 'collage', 'path': '<collage path>'}

A `session` ref emits `<recalled ref= session= at= kind= ok=>`. A `collage` ref emits `<recalled-notebook path= cells=>` wrapping the collage's cells through `_context_cell`. Every cell arrives with its `compact=` and `origin=`.

### Pruning it automatically

`compact_notebook_context` currently matches `<notebook[^>]*>` and prunes the cells inside it. It gains a tag list and runs over `<recalled-notebook>` before `<notebook>`. Recalled context is older and less certain than the notebook the user is looking at, and when something has to go it should go first. The `<context-compacted />` marker gains the tag it applied to, which is how the model tells which block shrank.

This ordering is the one behavioural decision in the collage design worth arguing about. The alternative, treating both blocks as one pool, means a `keep` cell in a collage from March can survive at the cost of an `auto` cell the user ran two minutes ago. The ordering above prevents that, and a user who disagrees marks the collage cell `keep`, which still wins within its block.

### Seeding a prompt cell

`Workspace._agent_context(nb, i, prompt, agent)` gains a collage lookup. A notebook holds `metadata.leela.collage` naming a collage path, set from a tab menu item, and `_agent_context` prepends that collage's `<recalled-notebook>` block to `nb.context(i)`.

That is the whole of "a prompt cell that starts loaded and then uses the current notebook". The prompt cell already reads from the top of its document. It now reads from a collage first.

Two smaller pieces make the one-block-at-a-time working style real. `add_cell` already exists as a tool, and the prompt-cell briefing gains an instruction to propose the next cell rather than a finished notebook. And `/recall/suggest` runs `recall_search` on the prompt cell's own text before the turn and returns rows for the composer. The user attaches before asking rather than after being told the agent has no context.

## Two agents, in dhrishti

### Named sessions

`agent_session(name='default')` keeps a dict rather than a singleton and returns the session for `name`, creating it on first call. `AgentSession.__init__` takes `name`, defaults its transcript to `agent_<stamp>_<name>.ipynb`, and records the name on every cell it logs.

`/agent/api/*` endpoints take an optional `agent=` parameter selecting the session, defaulting to `default`, which leaves every current client working unchanged.

### Three layers, not two

Today there is the owner namespace and one agent layer. There are now three:

| layer | who writes | who reads | how |
|---|---|---|---|
| owner | the human | everyone | the kernel, or `/api/exec` with the token |
| shared | any agent, by publishing | everyone | `session.publish(name)` |
| private | one agent | that agent | any bind in `run` |

`_sync_in` seeds the run namespace with owner names, then shared names, then the session's own layer, in that order. A private name shadows a shared one, and a shared one shadows nothing the owner holds. `owner_names()` keeps its current meaning and continues to protect only the owner's bindings.

`publish(name)` moves a name from `self.layer` into the process-wide shared dict and records the publishing session. It refuses when another session already published that name, naming the owner in the error, because silently overwriting a peer's variable is the failure this is being built to prevent. `unpublish(name)` is allowed only to the publisher.

Publication is agent to agent and needs no token. Promotion is agent to human, reaches the owner's namespace, and keeps the token gate it has today. Keeping those two separate is what lets peers share work without widening the boundary the token exists to hold.

A new tool pair joins `agent_tools`: `publish_var(name)` and `list_peers()`, the second returning each live session's name and its published names.

### Authorship in the transcript

`log_run` gains a `meta` parameter merged into the cell's `metadata` under a `dhrishti` key, and `AgentSession._log` passes `{'agent': self.name}`. `log_md` does the same. `read_agent_session` returns the metadata alongside `cell_type` and `source`.

Leela renders the author as a gutter label on the cell, reading `metadata.dhrishti.agent` the way it reads `metadata.leela.context`. A transcript stays a valid notebook that Jupyter opens.

### The lock

Two locks, both narrow.

`AgentSession` holds an `RLock` taken across `_sync_in`, `exec` and `_sync_out` in `run`. Without it two concurrent runs interleave their namespace synchronisation and the second `_sync_out` writes back names the first never saw.

`log_run` takes a per-path lock from a module-level `WeakValueDictionary` keyed on the resolved path. The read-modify-write of the whole notebook file is not atomic, and two agents in one session write to one path by construction. The bare `except: pass` stays, since a failed log must never break a run, but it gains a counter that `/agent/api/info` reports, because a transcript that silently stops recording is worse than one that says it dropped four cells.

Cross-process writers to one transcript are out of scope. The lock covers threads in the process that owns the namespace, which is where the two agents are.

## Staging

Each stage is useful alone and none depends on a later one.

1. `SessionIndex`, the three `Host` methods, `recall_tools`, and the scan backend. Ramabana only, testable with `fake_agent` and fixture logs.
2. The dhrishti lock and cell authorship. Independent of everything else, and it fixes a live defect.
3. `/recall/search` and the results panel, with `kind: 'session'` attachment. Leela gets recall into a turn with no collage yet.
4. The collage document, `origin` on `Cell`, `<recalled-notebook>`, and the `compact_notebook_context` tag list.
5. Prompt-cell seeding and `/recall/suggest`.
6. Named dhrishti sessions, the shared layer, `publish_var`, and `list_peers`.

Stage 6 is the one to defer if any should be. Two agents over two overlays with an explicit publish is the right design, and the demand for it is unproven. `docs/parallel-threads.md` already argues that the per-thread cost is a kernel and a kosha index, and two agents in one namespace saves that cost at the price of a write-conflict surface. Stage 2 is worth doing regardless, because the unsafe sharing exists today whether or not anyone asked for it.

## Testing

Ramabana, in `tests/test_recall.py` against fixture logs, in the hand-written pytest style the suite already uses:

- A fragment ref round-trips: `recall_read(f.ref)` returns the fragment `recall_search` produced.
- A failed turn ranks below a successful turn with the same query overlap, and `outcome='failed'` returns it.
- `tools_for` omits the recall group for a host that raises `NotImplementedError` from `recall_outline`, and includes it for one that answers.
- `budget_for` on a 16k model drops recall along with memory and web.
- A malformed line in the JSONL is skipped rather than raising, since the log is appended to under `except: pass` and a truncated final line is the normal crash artifact.

Ramabana notebook cells in `16_recall.ipynb` carry the readable `test_eq` examples, per the division the repository keeps.

`compact_notebook_context` gains cases in `01_runtime.ipynb`: a prompt with both a `<recalled-notebook>` and a `<notebook>` loses recalled `discard` cells first, then recalled `auto`, then notebook `discard`, and a `keep` cell in either block survives until nothing else is left.

Leela, in `tests/test_agent.py`:

- `_attachment_context` on a `session` ref emits `<recalled ref=>` with the fragment text.
- A collage attachment emits one `<cell>` per collage cell, each carrying `compact=` and `origin=`.
- `_agent_context` on a notebook with a collage in its metadata puts the recalled block before the notebook block.
- A collage saved and reloaded keeps `origin` and `context` on every cell.

Dhrishti, in the notebook tests:

- Two threads calling `session.run` with distinct binds both leave their names in the layer, which is the lock's regression test and fails today.
- Sixty concurrent `log_run` calls on one path produce sixty cells.
- `publish` from session A makes the name readable in session B and refuses a second publish from B, naming A.
- A published name does not appear in `owner_names()` and cannot be rebound by a non-publisher.
- A transcript cell carries `metadata.dhrishti.agent`, and `read_nb` still parses the file.

## Out of scope

Editing a past session. A transcript is a record, and a collage is where a rewrite goes.

Cross-machine or cross-user recall. The stores are files under one config directory.

Embedding session fragments into the code index. Kosha holds code and vishalakshi holds prose, and the consolidation note in `docs/consolidation.md` keeps that split. Session fragments are prose with code in them, and they go to the vault.

Automatic collage building. An agent may add to a collage through the tools it has, and nothing assembles one on its own. A retrieval system that decides unasked what an agent remembers is a different design with a different failure mode.

A second path to `/api/promote`. Publication between agents is new. Promotion into the owner's namespace keeps exactly the gate it has.
