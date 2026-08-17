# Changelog
copilot access
subagent write access and bettwer tool call instructions
release
tool_channel asks the live chat, so an agent harness carrying tools natively is no longer sized and briefed as if it were on tags
openapi spec changes 
release
allow max tool calls auto
image support and openapi spec support

make system prompts tighter and show one line tool calls

kosha sync made faster

Shri Rama jayam. Ramabana relase

Half the sandbox, a row of options, and the terminal app's hands back -- plus a pass over
everything the harness was leaving on the table in the four libraries underneath it.

### New

- `ramabana --python`: a Python prompt whose namespace is yours, with the agent reading it through
  Dhrishti's sandboxed overlay and unable to rebind anything it did not create. It is a mode of the
  one terminal rather than a second program -- `/python` starts the kernel and takes the line,
  `/agent` hands it back, and everything else about the surface is unchanged. `--attach` locks into
  a kernel that is already serving, which is how it runs inside leela.

### Added

- **`ask_memory`**, and `Host.ask` behind it -- ask remembered research a question and get a
  short cited answer rather than the sections. The same trade `delegate_search` makes: reading
  the material yourself costs every section of every candidate document in your context.
  It appears only for a host that implements `Host.ask`.
- **Private material is answered on this machine.** When the sections a question retrieved hold
  personal information -- decided arithmetically by `vishalakshi.pii`, never by asking a model to
  read it first -- the answer is computed by a local model under a briefing that forbids it
  repeating any personal detail to the caller. It says what it is holding and what instruction
  would let it answer usefully; the caller sends that back as `instruction` and it gets another
  turn on the same sections. The runtime is checked on the chat object before a character is
  sent, so a lent hosted chat is refused rather than trusted, and `pii='off'` is deliberately
  not reachable from the far end of a tool call.
- `Agent.lend_model`'s factory honours the model it is asked for (`Agent._spec_for`), which is
  what makes "the local one" mean it.
- **`Host.capabilities`** -- a host declares which tool groups it supports, and `tools_for`
  asks before it probes. The probe is the first thing to touch a host, so a capability whose
  answer sits behind a model load is one the probe waits through: `VaultHost` opens its vault
  in the background precisely so the tool list does not wait, and `memory_tree('')` then
  blocked on the lock that thread holds. 3.0s against a stub, a whole embedding model against
  a real one, on the first `Agent.tools` access.
- **`Agent.poll_watches`** and `Agent(poll_every=)` -- the tick the watch feature was built
  around and nothing ever called. A turn is the tick, in a daemon thread; whatever fires files
  itself into memory. `VaultHost.connect` is the same move for the entity graph, which
  `research` used to rebuild inline on the one path where the user is definitely waiting.
- **`Host.grep`** -- a host with a fast exact matcher answers it, and `LocalHost` does through
  ripgrep, covering exactly the files `walk` yields. The tool read every file through
  `host.read`, and therefore `check`, and therefore a `resolve` per file.
- **`Agent.snapshot_tree`** and `SHELL_SNAPSHOT` -- `changes()` keyed on a tool argument named
  `path`, and `run_shell` has none, so a command that rewrote twenty files reported `{}`.
- **`LocalHost(rerank=, rerank_model=)`** -- Kosha's cross-encoder, wired through to both
  context calls. It falls back once and stops asking if flashrank cannot fetch its model.
- **`LocalHost.indexed`** -- per-folder index readiness, so a small repo goes semantic while a
  large one is still syncing. `index_ready` is now "all of them".
- **An `oneshot` routing job**, and `Routing.spec` falling back when a job's model is not
  installed here. `inline`, `completion`, `classify` and `summary` take it unless singled out.
- **`Agent.lend_model`** and `VaultHost(mk_chat=)` -- vishalakshi builds a chat per `ask`, which
  on a local model is a second copy of an engine already in memory, answering on a different
  model from the one being talked to.
- **`core.claude_tags`** and `$RAMABANA_CLAUDE_TAG_TOOLS` -- Claude Code declares tools as an
  in-process MCP server and an enterprise-managed configuration forbids every dynamic MCP
  server, so the tools were stripped and the model ran blind. They travel in the system prompt
  instead, through Rishi's `tool_mode='tags'`.
- **`LocalHost(read_outside=True)`** -- the sandbox has two halves and only one of them is
  usually the point. Confining *writes* stops an agent damaging something nobody opened;
  confining *reads* stops it answering a question whose answer is in a sibling checkout or a
  library outside the venv. With this on, a read may name any path on the machine and a write
  may not. Enumeration is unchanged either way -- `walk`, and therefore `grep` and
  `list_files`, never leave the open folders -- so a read outside is always a path the model
  already knew, never one it found by looking. `DENY` is the short list of credential paths
  refused regardless, because opening the sandbox is a decision about source and not about
  the user's keys. `--read_outside` on both `ramabana` and `ramabana-mcp`.
- `Host.check` takes `reading=`, and the read-only tools resolve through the new
  `tools.readable`, which checks the signature first -- so the flag is a host capability
  rather than a tool assumption and a host written before it sees the call it always saw.
- **`cli.Option` / `options_for` / a reworked `ChoiceMenu`** -- the two-choice refactor prompt
  became a component. A prompt whose *reading* matters gets a titled row of options above the
  input line, each with the instruction it appends; arrows, digits or the option's own letter
  pick one, and cancelling hands the typed line back to the composer instead of dropping it.
- `cli.mk_host`, and `--vault` on both frontends: durable memory through `VaultHost` was
  reachable only by writing Python, so neither frontend could use vishalakshi at all.
- **Attachments** in `ramabana.cli` -- `MEDIA`, `Attachment`, `media_path`, `media_paths`,
  `attach_refs`, `media_parts`, `media_note`, and `Ui.attach`/`detach`/`attach_row`. A prompt
  now carries up to `MAX_ATTACH` files, images *and* audio, named the way a terminal already
  hands files over: dropped on the window, pasted as a path, or written `@path` in the
  sentence. Every shape a terminal delivers a drop in resolves to the same attachment --
  quoted, bracketed, a `file://` URI, spaces backslash-escaped, several at once -- where
  before only a bare unquoted path did, which is why dropping a picture on the prompt
  usually just typed its path. Pictures go out as content parts; *every* attachment is also
  named by absolute path, so a runtime with no ear for audio can still reach a `.wav`
  through the file tools. Chips above the prompt say what the next message will carry, and
  the turn that named them is the only one that carries them.
- **`Ui.attach_clipboard` and `clipboard_png`**, on `ctrl+v` and `/paste`. Bracketed paste
  carries text and only text, so a copied *image* never arrived as input at all; the picture
  has to be asked of the platform (`pngpaste`, `wl-paste`, `xclip`), and a missing helper is
  a plain sentence rather than a silent no-op.
- **`Ui.copy_last`, on `/copy`** -- the newest reply to the system clipboard over OSC 52,
  without leaving the prompt for the transcript view to get it.
- `Ui.note`, `Ui.touch`, and `Ui.enter_transcript`/`leave_transcript`.

### Fixed

- **`Agent.changes()` was blind to `run_shell`.** It keyed on a tool argument called `path`,
  and a command names no files: `black .`, a codemod, a `git checkout` can rewrite twenty
  files and mention none of them, and the answer came back `{}` -- worse than a gap, because
  the README points at `changes()` as the thing that knows what moved.
- **`_named` dropped the positional half of a mixed call.** `args = kw if kw else _named(f, a)`,
  so `edit_file('a.py', commands=...)` was recorded with no path -- an unreadable activity line,
  and a file that was never snapshotted, because the path `changes()` looks for is that one.
- **`LocalHost.search` tried its legs in order instead of fusing them**, so a rename whose query
  happened to embed well lost its own call sites. Both run and `fossick.rrf` merges them.
- **`read_url` promised "(or GitHub file, arxiv paper)" and plain-fetched both.** It routes to
  fossick's own readers now, and escalates through `fetch(auto=True)` -- plain, heavy, stealthy,
  logged-in Chrome -- rather than jumping hand-rolled from plain to a stealth browser.
- **Kosha was told to sync serially** (`in_parallel=False`, overriding its own default, for no
  reason anyone wrote down), which is why `index_ready` took minutes and every search until
  then was literal.
- **`resolve` checked `runtime_available` for a `vendor/model` name and not for a short one**, so
  `resolve('qwen-4b')` succeeded on a machine with no MLX; the job built a backend, `start()`
  failed, and `Agent.oneshot` returned `''`. The cheap jobs did not error -- they stopped
  happening.
- **`LocalHost(roots=())` raised `IndexError` out of `check`.** It is a legal host; it refuses
  paths with an `AgentError` that says why.
- **`ramabana.core` wrote into `sys.modules` at import time**, rearranging `toolslm` for every
  other consumer in the interpreter because somebody imported this library to read a constant.
  The shim is installed at the two points that need it.
- **`scale_numeric` is gone** -- a pandas min-max scaler in the permanent tool list of a general
  coding harness, which is what `coding_patterns` says not to do.
- **`RishiBackend` reached into five Rishi privates** (`_oneshot`, `_sys_pre`, `toolspecs`, `ns`,
  `_recreate_conv`). Rishi grew `Chat.oneshot` and `Chat.reconfigure`; `think=False` now applies
  on every runtime rather than only MLX.
- `LlamaBackend` and `FastllmBackend` warn as deprecated aliases for `RishiBackend`.
- `pyproject` refused to install below 3.12 while its classifiers claimed only "Python 3".
- **An attached image shredded the rest of the message.** `compose` returns a list of content
  parts when there is an image, and `_prepare` then did `list += str` -- which extends a list
  one character at a time. Every multimodal turn reached the model as the image followed by
  several hundred single-character parts, with the tool plan and every preflight result
  scattered among them.
- `Approvals` refusals that nobody could be asked about (`mode='off'`, or no listener
  registered) never reached `on_answer`, so the reason existed only in the model's context
  and the user saw an unexplained tool failure.
- `Agent.checkpoints` grew for the life of a session, holding a deep copy of a whole
  conversation per turn. Capped at `MAX_CHECKPOINTS`.
- `/skill NAME` was `return self.oneshot and clip(...)` -- a bound method used as a truth
  value, left over from an earlier shape.
- The briefing and `tool_plan` still named leela, telling a model working on any other
  project about an editor that is not there.
- `captured` read `$LEELA_NO_NATIVE_CAPTURE` directly, so the switch was unreachable under
  the prefix `use_env_prefix` exists to set. It goes through `env` now, and the old name
  still works as the fallback.
- The activity feed had no summary or icon for `run_shell`, `grep`, `ls`, `replace_text`,
  `create_skill` or any of the memory, watch and cart tools -- the shell call, which is the
  one a person most wants to read back, rendered as `run_shell(command='…')` under a wrench.
- `Ui.submit` tested for a refactor question *before* recognising a slash command, so
  `/model refactor-thing` opened a menu instead of running.
- `_supports` was written as a general capability probe and hard-coded `run_cmd` in its body.
- With an agent, the MCP server now mounts the agent's own recorded tools, which is what its
  documentation already claimed: a client's call lands in the same activity feed and the same
  `changes()` as a call the model made for itself.
- **The code index never built the call graph it searches through.** `sync_index` passed
  `sync_graph=force` -- kosha's *deprecated* name for `graph`, and `force` is `False` -- so
  every ordinary sync ran with `graph=False`, while `_semantic` went on asking
  `Kosha.context` for graph expansion over a graph that was not there.
- `LocalHost.web_search` sliced fossick's results to `n` instead of asking for `n`, and
  fossick's own default is 10 -- so a request for twenty results returned ten.
- `LocalHost.research` stringified the whole `{query, sources, digest, dropped}` record
  fossick returns. `digest` *is* the cited markdown and `sources` is the same markdown again
  per page, so the model was handed both copies wrapped in Python dict syntax.
- Four tests asserted against `fastllm.chat` privates (`_alite_call_func`, `AsyncChat.tcdict`)
  for a shim this package no longer installs, and had been failing since that library changed
  shape. Replaced with tests of the approval behaviour they were really protecting.
- **Copying a reply returned the screen, not the reply.** No block passed Teleprint a
  `source`, and `set_body` clears it unless given one, so `y` and search fell back to
  scraping the rendering: prose re-wrapped to the terminal's width, code indented by the
  gutter and stripped of the fences that made it paste-able. Every block now states its own
  text, and a plain string or `Text` states it for free.
- **The transcript view froze during a turn.** It is entered pinned to the tail (`less +F`)
  but nothing ever called `TranscriptView.notify`, and `set_tail` goes model-only while the
  alt screen owns the tty -- so a streaming reply, arriving tool calls, and the status bar
  itself all stopped until the next keystroke. `Ui.touch` and `Ui.paint` now drive it, rate
  limited by `NOTIFY_EVERY` because a rebuild re-renders every block in the model.
- **Mouse reporting was on everywhere, which took drag-select away from the terminal** --
  the ordinary way anyone copies out of a scrollback -- and in the main screen spent it on
  nothing but accidental fold toggles. It is now switched on only while the transcript view
  is up, which is Teleprint's own division: the main screen belongs to the terminal.
- `/help` described keys the app does not have: `↑`/`↓` enter the transcript rather than
  walking prompt history (that is `ctrl+p`/`ctrl+n`), and `ctrl+y` yanks.
- The attachment hint overwrote the roots hint permanently and outlived the turn it
  described, so the status line went on claiming an image was attached after it was sent.
- Cancelling the refactor menu with `esc` discarded the prompt that opened it; it now
  returns to the composer.

## 0.1.1
Memory that outlives the process, and the first extension that spends money.

### Added

- `ramabana.vault.VaultHost` -- `LocalHost` with a
  [vishalakshi](https://github.com/vedicreader/vishalakshi) vault behind it. Three things
  follow from one SQLite file: the five `memory_*` tools finally have something to answer
  from, so `tools_for` stops dropping them; `search_code` fuses the vault's prose with
  kosha's identifiers and ripgrep's literals by RRF rather than by distance, since the legs
  share no vector space; and `read_url`/`research` file what they fetch, so what the model
  reads and what the next session can recall are the same text. A vault that will not open
  degrades to exactly what `LocalHost` already did.
- **Standing interests on `Host`** -- `remember`, `watch`, `watches`, `unwatch` and `poll`,
  with `watch_tools` behind the same capability probe every other group uses. A reminder is
  a watch whose action files its own text back into memory when it comes due, so "what am I
  supposed to be doing" and "what do I know" are one query and neither needs a notification
  channel the harness does not own. One failing watch is recorded on its row, not raised.
- `ramabana.shop` -- `Cart`, `FossickCart` (a real logged-in Chrome via `fossick.shop`),
  `FakeCart`, and `cart_tools`. Registered as an extension rather than added to `Host`: an
  agent editing a repo has no business holding a trolley. `cart_add` reports whether the
  cart actually moved rather than whether the click worked.
- `08_shop.ipynb` runs the whole thing end to end -- a reminder set once, polled a week
  later, and acted on across two stores -- with only the model's decisions and the trolley
  mocked.

### Changed

- `WRITE_TOOLS` gains `cancel_watch`, `cart_add` and `cart_remove`. The line an `Approvals`
  policy draws is no longer only around the filesystem: deleting someone's standing reminder
  and spending their money both belong in front of a person.

## 0.1.0

The nbdev source became honest again, and the harness grew two frontends of its own.

### Breaking

- **Modules consolidated to match the documentation pages.** Each notebook is now exactly
  one module, which is the only shape `nbdev-export` can produce idempotently. Old imports
  map as follows; the names exported from `ramabana` itself are unchanged.

  | was | now |
  |---|---|
  | `ramabana.models` | `ramabana.core` |
  | `ramabana.native`, `.compact`, `.backend` | `ramabana.runtime` |
  | `ramabana.host`, `.skills`, `.extensions`, `.subagent` | `ramabana.tools` |
  | `ramabana.activity`, `.hitl`, `.fastllm_hitl`, `.chat` | `ramabana.agent` |

### Added

- `ramabana.tools.LocalHost` -- a `Host` over real folders and a live namespace in-process:
  sandboxed path resolution (`..` and symlinks resolved *before* the check), automatic
  `Kosha.sync` in a daemon thread, repo-first semantic + keyword search across the open
  repository and installed packages, `ast`-based symbols and peers, notebook cells, and a
  persistent exec namespace. The reference implementation, and what both frontends run on.
- `ramabana.cli` -- a terminal app on [teleprint](https://github.com/answerdotai/teleprint).
  Transcript of foldable blocks, live status bar, streaming replies, tool calls as blocks,
  and the approval gate on the input line. `ramabana` and `ramabana -p 'one question'`.
- `ramabana.mcp` -- the same tools served over MCP, read-only by default, plus an `ask` tool
  that runs a whole Ramabana turn when a model is configured. `ramabana-mcp`.
- `ramabana.testing.FullHost` -- a host with *every* capability present over a throwaway
  folder, including a research-memory index and a web that returns the pages it was given,
  so the whole tool surface has somewhere to be tested. Its release check loads a real MLX
  model through rishi and verifies all 28 tool functions and all 28 compiled tool schemas.
- `ramabana.runtime.answer_only` -- strips a reasoning model's thinking from a one-shot reply.
- `ramabana.runtime.prefills_think` / `ThinkFilter` -- the streaming half of the same problem.
  `prefills_think` asks a model's own chat template whether it opens a `<think>` block and
  leaves the model to close it; `ThinkFilter` drops that block out of a streamed turn, and
  re-arms at every tool call because such a template opens a fresh thought per step.
- `ramabana.tools.ld_json` -- a page's `schema.org` JSON-LD blocks, which is where a product
  page actually states its price. `LocalHost.read_url` now prepends them to the prose.
- `mini-coder-4b` (`mlx-community/mini-coder-4b-OptiQ-4bit`) joins the MLX table and becomes
  the default for inline `completion`: a 4B trained on code finishes a line better, and
  faster, than a general 9B. Every other cheap job stays on the default local model.

### Fixed

- **Reasoning models broke every cheap job.** `classify`, `summarise`, `Completer` and
  compaction all read a one-shot reply as data, and all four returned the model's `<think>`
  block instead of its answer. `Backend.oneshot` now strips it, including the unpaired
  closing tag that is what actually arrives when the chat template opens the block in the
  prompt.
- **Inline completion could insert prose into your file.** A small model asked for bare code
  explains itself first and then opens a fence the token cap cuts off before it closes;
  `_clean` took the whole reply. It now keeps only what follows an unterminated fence, and
  suggests nothing when there is nothing but prose.
- `nbdev-export` works again (it raised `TypeError` in `nbdev/maker.py`), is idempotent, and
  the custom `tools/export.py` that had replaced it is gone. `nbdev-clean` is a no-op,
  `nbdev-test` executes every notebook, and generated modules carry the `AUTOGENERATED`
  header, real `__all__` lists, module docstrings and doclinks again.
- Relative imports in exported cells (`from .core import ...`), which `nbdev-export` refuses.
- **A streamed turn leaked the model's thinking into the reply.** Rishi's splitter waits for an
  opening `<think>` to know it is inside a thought, so a model whose chat template writes that
  tag into the generation prompt -- Ornith-1.0-9B, among others -- never emits one, and its
  deliberation arrived as ordinary reply text with a stray `</think>` in the middle of it.
  `_stream` now filters the structured chunk stream and renders what is left with Rishi's own
  formatter. This was the release's one *Known* limitation, and it is gone.
- **A cheap job could not answer at all inside its own budget.** `classify` allows thirty-two
  output tokens; a reasoning model spends all thirty-two thinking, so there was no answer left
  for `answer_only` to uncover. The one-shot conversation is now built with `think=False`,
  which closes the template's thinking block in the *prompt* -- the model answers immediately.
- **The first cheap job capped every one after it.** `_oneshot_chat` is reused across jobs and
  was constructed with the first caller's `max_output_tokens`, so a 32-token `classify` left a
  32-token ceiling behind and the next `summarise` came back cut off mid-sentence. Each call
  now passes its own cap explicitly.
- **`read_url` could not read a page that renders in the browser.** A site that turns away
  scrapers answers `200 OK` with an empty shell rather than an error, so escalating on the
  status code never fires. `LocalHost.read_url` judges the extracted *text* instead and
  escalates to a real browser only when there is too little of it to be a page.
- `local_ctx('ornith-9b')` silently returned the fallback window: the table keyed it
  `ornith_9b`, with an underscore, while the model alias has a hyphen.

### Docs

- Every notebook is a literate page: sections with exported summaries that assemble into the
  module docstring, and executable examples that double as the tests -- including the terminal
  UI, asserted against a headless terminal emulator, and the MCP server, asserted through
  real `list_tools`/`call_tool` round trips.
- `nbs/index.ipynb` ends on one real problem solved end to end: a routed agent over this
  repository and the live web, finding a constant with the code index and a supermarket price
  through a browser, and closing on arithmetic that needs both. The turn runs on a hosted
  model, every cheap job on a local MLX one. Those cells are `eval: false` with their real
  outputs stored, so neither CI nor the docs build needs a GPU or a network.
