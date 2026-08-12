# pyrepl: a Python REPL you own, with an agent in the next layer

Date: 2026-08-12
Status: approved, ready to plan

## What this is

`ramabana pyrepl` is one terminal holding two things: a Python prompt whose namespace belongs to
the person typing, and a Ramabana agent that can read that namespace and build in a layer above
it. Neither can overwrite the other's names. Dhrishti is what makes that true, and it is already
written — this is the assembly, not the mechanism.

There is prior art on disk. `reference/pyrepl.py` and `reference/cli.py` are a working
implementation from before a merge dropped it, `tests/test_pyrepl.py` pins its contract, and
`.ramabana/pyrepl/agents/agent_20260812-082250.ipynb` is a transcript from a real run of it. The
design below is that implementation, reconciled with the current tree and extended with an attach
mode. It is not a fresh design and should not be treated as one.

## Why the layering is not ours to enforce

Dhrishti serves a live namespace over HTTP and splits it in two:

- The **owner endpoints** — `/api/exec`, `/api/set`, `/api/promote` — mutate real state and are
  gated by a per-server token written to `<reg_dir>/token-<port>` at mode 0600.
- The **agent endpoints** under `/agent/` are ungated, and with `agent='restricted'` they give a
  sandboxed overlay: reads reach any owner variable, writes land in the agent's own layer, and
  mutating or deleting an owner binding is refused.

So "the agent reads but never rebinds" is enforced by the process that owns the namespace, not by
ramabana asking nicely. Ramabana's whole contribution is to point its Python tools at the `/agent/`
half and never hold the token. The blocked-mutation comment in the surviving transcript
(`# blocked: 'sp += ...' may mutate the owner's object in place; use a new name`) is dhrishti
talking, and that is the right author for it.

## Components

### `Kernel`

A private `ipykernel` under `AsyncKernelManager`, ipc transport where the platform has it, started
in the project root. Its one unusual job is `_bootstrap`: it executes a snippet *inside* the kernel
that calls `dhrishti.serving.serve_in_kernel(name='ramabana pyrepl', agent='restricted', token=True,
session_dir=…, agent_session_dir=…)` and prints the bound port behind a marker, which the parent
parses into `self.base`. The server has to start inside the kernel because the namespace it serves
is the kernel's, and it runs on a background thread so it keeps answering during a long cell.

Beyond that it is an nbformat adapter: `execute` returns an `ExecOutcome(ok, outputs,
execution_count, error)` where `outputs` are notebook-shaped dicts, coalescing consecutive streams
and honouring `update_display_data`, with an `on_output` callback so the UI can paint before the
cell finishes. It also exposes `complete` (for tab), `interrupt` (for ctrl-c) and `shutdown`.

### `output_text(outputs)`

Flattens notebook outputs to plain text for logs, tests and any surface that cannot render rich
output. Streams contribute their text, `execute_result`/`display_data` their `text/plain` (falling
back to `text/markdown`), and errors their traceback or `ename: evalue`.

### `DhrishtiHost(LocalHost)`

A ramabana `Host` — so every file, search and web tool is the ordinary one — whose *Python* tools
go over HTTP to the agent half of a dhrishti server:

| host method | endpoint |
|---|---|
| `run_python` | `/agent/api/exec?scope=overlay` |
| `inspect_python` | `/agent/api/exec?scope=isolated\|overlay` |
| `list_vars` | `/agent/api/rows?profile=minimal&sort=name` |
| `agent_log` | `/agent/api/info` → the session notebook path |

`scopes` is `('isolated', 'overlay')` and `kernel_kind` is `'ipykernel'`, which is how `tools_for`
decides the session tools are present. It takes `base` as its second positional argument and
forwards everything else to `LocalHost`, so `web=` and `index=` behave as they do anywhere else.

`log_cell(source, outputs=None, cell_type='code')` appends to dhrishti's session notebook: the
owner's executed cells as code cells carrying their real outputs, and each turn as
`**user**` / `**assistant**` markdown. That interleaving is the point — one file is the whole
session, and it is the file the earlier run produced.

### `PyreplUi(Ui)`

The existing terminal surface — blocks, gutters, folding, the status bar, approvals, `/copy`,
transcript navigation — with a `mode` of `python` or `agent`. **Python is the default**, because
this is a REPL that has an agent in it rather than an agent that has a REPL in it. `/python` and
`/agent` switch; the prompt label and status colour say which is live. Two keys change meaning in
python mode: `tab` completes through the kernel, and `ctrl-c` interrupts the running cell rather
than the model.

Two drivers sit under it. `run_code` executes an owner cell, streams outputs into blocks through
`on_output`, and logs the cell. `run_agent` streams a model turn on a worker thread, pumping chunks
back over a queue onto the loop, and logs the user prompt and the reply as markdown.

### Entry points

`cli.main` gains a `prompt == 'pyrepl'` dispatch that forwards the current option set. The import
lives in the function body so `pyrepl.main` is resolved through the module at call time, which is
what lets `tests/test_pyrepl.py` monkeypatch it.

## The two shapes

**Own kernel** — `ramabana pyrepl`. Starts a `Kernel`, bootstraps dhrishti in it, builds a
`DhrishtiHost` on its base and runs the full `PyreplUi`. This process is the owner: it armed the
token, so adopting an agent variable is legitimate here.

> The one thing in this spec that is **not** in the reference implementation: a `/promote <name>`
> command for own-kernel mode, calling the token-gated `/api/promote`. Without it an agent's
> variable can never be adopted, which is most of why the layering is worth having — but it is new
> surface area rather than restored surface area, and it can be cut from the first pass without
> affecting anything else here.

**Attach** — `ramabana pyrepl --attach <name-or-url>`: locking into a kernel that already has an
agent session, which is the case that matters when ramabana runs inside leela. A bare name is
resolved against `dhrishti.serving.active()` by the registry entry's `name`, matching leela's
`env_name`; anything with a scheme is taken as the base URL. It builds only the `DhrishtiHost` and
an `Agent`, and runs the ordinary `Ui`. No `Kernel`, no python mode, and **the owner token is never
read**. Leela already owns the human's Python surface; ramabana
is purely the agent working the overlay beside it.

Attach must **not** call `serve_in_kernel` to discover the port. `_start` is guarded by
`if _server is None`, but the assignments above that guard are not: `_profile`, `_env` and
`_agent_mode` are reassigned unconditionally, and passing `session_dir`/`agent_session_dir` calls
`set_logging` regardless. Re-serving inside leela's kernel would therefore repoint leela's session
logs and reset its agent mode — quietly promoting a `readonly` session to `restricted`. Discovery
goes through the registry, which is read-only.

Promotion in attach mode is not ramabana's to perform. The agent's work is visible in the shared
session notebook and over the same API leela is already watching, and the human promotes from the
surface that holds the token. Ramabana does not add a request-and-confirm protocol for this; there
is nothing it could do that leela cannot already do better, and a second path to a mutating
endpoint is exactly what the token exists to prevent.

## Errors

Every host method returns a string, because a tool cannot raise usefully — a transport failure comes
back as `agent_err(exc)`, a dhrishti-reported error as its own message, and a successful statement
with no value as `(ok)`. A failed bootstrap raises, since a pyrepl with no dhrishti is not a
degraded pyrepl but a different program. A dead kernel answers `ExecOutcome(ok=False,
error='kernel is not running')` rather than hanging on iopub.

## Dependencies

`dhrishti` and `jupyter-client` go in a new `pyrepl` extra, imported lazily, so a plain ramabana
install is unaffected and the missing-dependency message names the extra — the same shape
`core.resolve` already uses for rishi's optional runtimes. `teleprint` and `rich` are already
present via `cli`.

## Testing

`tests/test_pyrepl.py` is the existing contract and is not to be rewritten to fit the code:

- `output_text` normalises a stream, an `execute_result` and an `error` into one string.
- `cli.main('pyrepl', …)` dispatches to `pyrepl.main` with `root`, `model` and `web` intact.
- The overlay test starts a real kernel, executes `owner_value = 40` as the owner, has the agent
  read it and create `agent_value`, checks the logged cell's outputs round-trip through the
  notebook, then rebinds `owner_value` from the agent layer and asserts the owner still sees `40`.

That last one needs a live kernel and dhrishti, so it skips when the `pyrepl` extra is absent.
The notebook adds surface tests in the established style: `PyreplUi` driven against a `pyghostty`
emulator with a `FakeBackend`, covering mode switching, the prompt label, python-mode `tab` and
`ctrl-c`, and `on_output` rendering each output kind into the right block.

## Reconciliation notes

The reference predates the current tree in three ways, all mechanical: it is tab-indented against a
space-indented repo; it declares `../nbs/10_pyrepl.ipynb` while `10` is now `10_spec.ipynb`, so the
notebook becomes `11_pyrepl.ipynb`; and its `main` lacks `read_outside` and `vault`, which the
current `cli.main` has and the dispatch must forward.

## Out of scope

Promotion from attach mode. A request-and-confirm protocol between ramabana and leela. Any UI in
dhrishti. Replacing leela's Python surface.
