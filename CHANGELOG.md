# Release notes

<!-- do not remove -->

## 0.2.89
- The morning report of work together mode has its examples and actions again. It made its summary with the pair that `mk_agent` returns, not the agent, and said "the summary model failed: 'tuple' object has no attribute 'oneshot'" every time.

## 0.2.88
- An approval request that a host builds with the real arguments no longer shows a secret argument. Its row, its event, the turn history and the saved conversation show `[SECRET]`, and the summary and preview are made again from the hidden arguments. The approved call still runs with the real value.

## 0.2.87
- A tool can name secret arguments with `secret_args`, for example `add_exercise.secret_args = ('solution',)`. ramabana writes `[SECRET]` in their place in the call list, the activity rows, the approval card, the events and the saved conversation. The tool still gets the real value.

## 0.2.86
- Work together mode ends only when you type. A task notification or a subagent's hand-back that Claude Code sends as a prompt no longer ends it.
- A new session's beat starts at the newest note. Notes from before the session, such as old failures that are already fixed, no longer come back.
- The README says that plain `ramabana setup` does not install the peer hooks, and that a session that was running before the setup must restart to appear in `ramabana peers`.

## 0.2.85
- Claude Code, Codex and ramabana sessions on one Mac talk to each other. `ramabana peers` lists the live sessions with their folders. `ramabana tell TARGET TEXT` sends a note, and `--ask` sends work that needs a reply. TARGET is a list number, a session id or a folder name. `--all` sends a note to every session.
- `ramabana setup peers --agent claude|codex|all` adds the peer hooks and the `peer-work` skill to Claude Code and Codex. It shows a diff and writes only when you say yes. `--remove` takes them out. The hooks run this ramabana's own Python, not the `ramabana` on `PATH`. `ramabana --doctor` checks that the hooks run and names a stale `ramabana` on `PATH`.
- A Claude session gets messages at your next prompt, keeps working while messages wait, and wakes when it is idle. Codex gets them when a turn starts or ends.
- An ask from another session always asks you first, also in `auto` mode. Every ask gets a reply: the answer, `refused:` or `failed:`.
- Work together mode: `ramabana together on --with abhyasa,leela --until 07:00`, or `/together`, lets those sessions send asks to you without approval. Each session keeps its own permission mode. The mode ends at that time, after 12 h, or when you type.
- Limits stop loops. A thread holds at most 6 messages: the ask and 5 replies. A session sends at most 40 notes and asks in 12 h.
- A session cannot edit files in a git repo that another live session works in. It sends that session a message instead.
- `ramabana report` gives the morning report: a table of what each session did, with its proof, plain examples, your actions and a glossary. It is saved when work together mode ends.
- The `peer-work` skill tells the sessions how to work for each other: read the repo's rules, agree the shape with the owner, show test output and a browser screenshot as proof, and let the owner review the diff.
- `/tell N --ask TEXT` sends an ask. The `tell()` tool takes `kind='note'` or `kind='ask'`.
- Needs shalya 0.1.24 and fossick 0.1.22.

## 0.2.84
- The terminal title names what ramabana is doing: `ramabana · idle`, `typing`, `running`, `waiting`, `approval`, `python`, `transcript` or `tasks`. The title changes only when that state changes. The hint row and the title get the state from one function, so they always agree.
- ramabana's own tmux server passes the pane title to the outer terminal (`set-titles on`, with `#{pane_title}`). Your own `~/.tmux.conf` does not change.
- The Sanketa keymap file has an optional `app_version` field, the ramabana version. A new version rewrites the file.

## 0.2.83
- ctrl+l, or `/tasks`, lists the background shells, sub-agents and watches, with each one's state and age. Enter opens one, `x` then `y` stops it, and Esc goes back with your typed text kept.
- While a turn runs, the working rows end with one short tip that names a key or command. It changes once per turn and hides while you type. `/tips off`, `tips = false` in `config.toml`, or `--no-tips` turns tips off; `/tips on --save` keeps the choice.
- One key table drives the key card, `/help`, `?`, the hint row and the tips, so they always name the same keys.
- At start, ramabana writes its keys to `~/.config/sanketa/keymaps/ramabana.json` (or `$SANKETA_KEYMAPS`), in Sanketa's keymap format 1, so Sanketa shows ramabana's current keys. It writes only when Sanketa is set up and only when the keys changed, and it never writes over a file that ramabana did not write.
- The help names alt+enter as the queue key. shift+enter still queues where the terminal sends it, but Leela's terminal does not.

## 0.2.82
- API keys in tool output are masked. Every read the model sees passes through a guard: files, search hits, diffs, web pages, and now shell and Python output too. Key shapes such as `sk-`, `ghp_`, `github_pat_`, `AKIA`, `AIza`, `hf_` and private-key blocks come back as `[SECRET]`. A write that would put `[SECRET]` over a real key is refused.
- The shell refuses commands that print the whole environment: `env`, `printenv`, bare `set`, `export -p`, `declare -x`, reading `/proc/*/environ`, and reading a `.env` file. Ask whether one variable is set instead.
- `--pii redact` and `--pii refuse` also cover shell, Python and web reads sent to a hosted model. Code reads keep their personal data, because edits need the exact text. `pii` in the `[cli]` table of `config.toml` sets it for every session; it is skipped when the vault is off.
- Sessions talk to each other. Every terminal session listens on its control socket. `/peers` lists the other live sessions by number and friendly name, `/tell N TEXT` sends a message to one, and `/tell N` sends each line you type there until `/tell main`. The agent has `peers()` and `tell()` tools; a `tell()` that starts a turn in another session asks you first.
- A message you queue during a turn runs on its own when the turn ends, before anything you type next. Before, a key typed at that moment could start first, and the queued message stayed in the queue and joined your next one.
- Up on an empty prompt takes back the newest waiting message, one per press. Alt+up still takes back all of them.
- Steered messages that the agent has not read yet show as rows under the transcript, and each row goes when the agent reads it.
- The hint row follows what you are doing: idle, typing, a running turn, waiting messages or an approval. `?` on an empty prompt shows every key. `hints = false` in `config.toml`, or `--no-hints`, hides the row.
- `auto` picks a light or dark theme from the terminal's background. Every palette name is a valid `theme`, `/theme` lists them, and `/theme NAME --save` keeps one in `config.toml`. The now pane and the sub-agent panes use the same palette, and follow `/theme`.
- A `!` command you stop ends with `stopped`, even when the shell reports its killed command as status 130 or 137.
- The `abhyasa` extra installs abhyasa with its `abhyasa-index` tick.
- Needs shalya 0.1.23.

## 0.2.81
- `read_outside` and `vault` in the `[cli]` table of `config.toml` turn on reads outside the open folders and the vishalakshi vault for every terminal session. `--no-read-outside` and `--no-vault` turn them off for one session. A session started with its own `--cfg` folder ignores both keys. The code defaults stay off, so Dhrona's replays and scratch runs do not change.
- A one-shot reply may use up to 8,192 tokens: a quarter of the model's window, and at least 1,024. A compaction summary may use up to 4,096 tokens. Before, both stopped at 1,024 tokens, which cut long answers and summaries short.
- The routing test in the core notebook reads an empty temporary `config.toml`, so a machine's own job settings cannot fail it.

## 0.2.80
- `--max-cost` stops a turn once it has cost that many dollars. It sets the agent's existing per-step cost stop, so the turn ends after the model step that passes the limit and is recorded with the state `budget`. Dhrona passes each replay the dollars left in its round and its night.
- The notebooks' `fake_agent` reads no skills or beat notes from the real home folder, so the notebook tests pass under any `HOME`.

## 0.2.79
- A tool call with a missing or unknown argument returns an error that names the tool, the argument and the expected parameters, so the model can call it again. Before, the tool raised `TypeError`; Dhrona counted 160 of these in 14 days.
- Calm mode for the terminal: each stretch of tool calls between two text blocks folds into one collapsed line, such as "3 tool calls · 1 file changed". Errors, approvals and questions stay visible. Turn it on with `calm = true` in `config.toml`, or for a session with `/calm`, `/calm on` and `/calm off`.
- Sessions load Dhrona's dated lessons (`dhrona-*.md`) after `AGENTS.md`, newest first, within 4,000 characters (2,000 for small models).
- `/learned accept` refuses only when an uncommitted change touches a file the lesson changes. An unrelated `AGENTS.md` edit no longer blocks it.
- When two lessons are kept on one day, only the newer pending branch is listed, and accepting it retires the older one.
- The `dhrona` extra needs dhrona 0.1.19.
- The test suite runs under a scratch home folder, so the machine's own configuration cannot fail it.

## 0.2.78
- `/rewind` puts a notebook back byte for byte. Before, it wrote the notebook's joined cell text over its JSON, which destroyed a notebook that a turn had edited with `edit_cell`.
- Shell writes are recorded when the open folders hold more than 32 MB of text. Before a command, Ramabana snapshots only the repositories that the command can touch. Before, it stopped watching shell commands above that size, so the Files pane and `/rewind` did not see files that a script or `nbdev-readme` wrote.
- The Files pane lists every file edited in the session, not only in the current turn. `/rewind` still undoes one turn.
- The `search` extra needs litesearch 0.1.61, koshas 0.1.18 and vishalakshi 0.1.35. litesearch 0.1.61 loads adhara, a native SQLite extension, and sets `ORT_DISABLE_TELEMETRY=1`. koshas 0.1.18 indexes the `lang:` filter.
- Needs shalya 0.1.22, whose `memory_search` tool says what `limit` counts.

## 0.2.77

- Needs shalya 0.1.21, uraiyadal 0.0.19 and rishi 0.1.56. The background code index writes in a child process. A crash in that child, such as the SIGBUS seen in SQLite, no longer stops Ramabana. A tool call that lacks a required argument returns a tool error and does not run.
- The `search` extra needs litesearch 0.1.59, koshas 0.1.17, vishalakshi 0.1.34 and fossick 0.1.21. Index writes commit in batches of 1,000 rows, and the WAL is truncated after each sync. The vault privacy gate fails closed on query errors. The `python` extra needs dhrishti 0.1.11. The base install needs gheasy 0.0.15.
- Default change: Folder reviews use the session's sub-agent step setting. Under `auto`, each review gets 80 steps. A numeric setting applies to the next review, up to 400. Before, folder reviews used the separate `REVIEW_MAX_STEPS` constant (12) instead of the session setting. The constant is removed. It was not a configuration key. Urai counts each approved tool call as one step. Quiet backends get twice the backend step budget for status calls. A separate read-tool allowance permits four calls per requested step.
- A turn stays active through verification, checkpointing and end-of-turn hooks. Before, Ramabana marked the turn finished before this work completed.
- A checkpoint write that raises `OSError` adds a warning to the answer. The answer keeps its result. Before, a checkpoint disk error replaced a successful answer with a failure note.
- A checkpoint pruning failure reports that the new checkpoint was saved but old checkpoints could not be removed. Before, an `OSError` during pruning reported that the new checkpoint was not saved.
- History compaction summarises only messages outside the recent history it keeps. It leaves the history unchanged when every message is recent. Before, it could summarise the whole history and then keep every original message too.
- Configuration updates preserve non-ASCII values in existing settings and table entries. Before, `set_setting` and `set_table` treated escaped values as regular-expression replacements and raised a bad-escape error.
- Configuration updates hold the file lock through the full read-modify-write operation. The lock allows nested acquisition by the same thread for the same resolved path. Before, the lock covered only the final write. Concurrent updates could lose settings.
- Compaction retries never use a larger input budget than the first attempt. Before, `halvings(128)` returned `[128, 256, 256]`. It now returns `[128, 128, 128]`.
- `config_reset(path)` preserves the `learning` setting from the file it resets. Before, it read that setting from the default configuration file instead.
- The code-index fingerprint for a non-git folder includes each visible file's relative path, size and nanosecond modification time throughout the folder tree. It skips hidden files and folders. Before, it used the maximum modification time of top-level entries and missed nested edits or edits below that maximum.
- Folder watches retry a failed initial snapshot on later syncs. They report the failure once until the watch recovers or is removed. Before, one snapshot failure excluded the watch from every later sync.
- Folder reviews record a delegation that does not complete as an error. Before, a failed delegation could appear as a successful review.
- Folder watches detect same-length edits to files too large to diff by including a content hash in the snapshot. Before, the snapshot kept only the file length for those files and missed same-length edits.
- The pane board retries a failed background-command status query after `SHELL_EVERY` (1 second). Before, it cached the failure as a final empty state and never asked again.
- Transcript panes remain tracked when tmux returns no pane list. Automatic closing waits for `PANE_LINGER` (3 seconds) before checking pane liveness. Failed checks retry at most once per second. Before, an empty pane list discarded the tracked pane. Automatic closing queried tmux on every tick.

## 0.2.76

- The `search` extra needs litesearch 0.1.56 and koshas 0.1.15. On macOS arm64 the embedding models tokenize and pool in Rust through laghu-rs and give the same vectors.
- `kosha embed` fills missing package vectors. `kosha prune` drops packages that no environment still has.

## 0.2.75

- The `search` extra needs litesearch 0.1.54, which loads embedding models with laghu. The default model takes 80 MB of private memory instead of 1,373 MB. It gives model2vec 0.9's vectors whatever model2vec version is installed.

## 0.2.74

- `ramabana history compact` (`compact_history`) shrinks the session history in place. Old prompts that hold picture bytes become `[image]`. Tool results over 600 characters move to `agent-details/`, as `_slim` now writes them. The command holds the history lock, keeps `.pre-compact` hard links unless you pass `--no-backup`, and rebuilds the session index. It refuses while another process holds a session, unless you pass `--force`. A copy of a 224 MB history came out at 65 MB, and every session hydrated identically.
- A history row still over `ROW_MAX` (1 MB) after slimming sends its prompt to the details file too; `hydrate_turns` restores it.
- `_append_line` re-opens the history if it was replaced while waiting for the lock. No row is lost to a replaced file.
- Needs rishi 0.1.55 and uraiyadal 0.0.17.
- A stray tag no longer drops a tool call's arguments.
- An unread call is never run.
- Identical calls in one reply run once.
- A tag quoted in an argument splits nothing.
- The `dhrona` extra needs dhrona 0.1.18, which reports the history's health each night.

## 0.2.73

- The `/pane` board keeps one transcript pane. A click on a run shows it in that pane, a click on `main` closes it, and a click on a finished or absent run opens nothing. Before, every click opened a new pane and none closed.
- A transcript pane closes `PANE_LINGER` (3) seconds after its run finishes or leaves the board, and a `/watch RUN` pane does the same. Only panes Ramabana opened are closed. Set `pane_close_done` (default on) to false to turn the automatic close off.

## 0.2.72

- Finished background work wakes an idle agent. When a background run that the agent started finishes and the user is idle, the terminal starts a turn with the result, logged as **background**. `auto_turns` is `on`, `report` (the turn reports without changing files) or `off`. The default is `on` under the edits and auto approval modes, and `report` under ask and off. The terminal starts at most `auto_turns_per_hour` (6) such turns an hour. It starts none for a cancelled run, and none while the user is typing or a turn runs.
- `delegate_tell(run_id, text)` sends a running sub-agent a message. The message arrives with the sub-agent's next tool result.
- `/talk RUN` sends what the user types to a sub-agent until `/talk main`. The status bar shows `→ run_x`. The target returns to main when the run ends. `/talk` completes `main` and the running ids.
- The `/pane` board lists `main` above the sub-agents and marks the current target. Clicking a row sets the target, and clicking a sub-agent opens its transcript to the left of the chat.

## 0.2.71

- A sub-agent reply with no tool call that is under 300 characters and has no `state:` line is sent back once with `SUB_NUDGE`, asking for the missing call or a final report. Before, a stray progress line ended a delegation as if it were the answer. A second such reply in a row is accepted, and the step limit still applies.
- Under the default `auto` step setting, a sub-agent's time limit grows with its steps: 20 seconds a step, never under `SUB_TIMEOUT` (30 minutes) or over `SUB_TIMEOUT_CEILING` (3 hours). A different `/subagents timeout` still wins, and 0 still means none.
- `ramabana.testing`'s fake sub-agents end their answer with `state: completed`.

## 0.2.70

- The `search` extra needs koshas 0.1.13 and litesearch 0.1.53, which index a project's packages from its own `.venv` and skip symlink loops.
- More notebook tests check behaviour, not wording.

## 0.2.69

- The sub-agent step setting is `auto` by default. Under `auto` a delegation's `max_steps` is honoured up to `SUB_STEP_CEILING` (400), and a delegation that names none gets 80. Before, every sub-agent was capped at 80 steps. A request for more fell back to 80 without a word.
- `/subagents steps N` takes 1 to 400, up from 80. It still caps every delegation. `/subagents steps auto` returns to the default.
- Under the `auto` tool budget each delegation's allowance is four tool calls a step, 1,600 calls in all. A 400-step sub-agent runs out of steps before it runs out of calls.
- Tests across `tests/` and the notebooks check behaviour, not message wording.

## 0.2.68

- Under the default `auto` tool budget, each top-level delegation has its own allowance of `_TOOL_MAX` (400) tool calls, shared with the sub-agents it starts. Before, every sub-agent of a turn drew from one pool of 400. After a few busy delegations, each later delegation in that turn was refused on its first call. A `delegate_async` or monitor run counts as one delegation with its children. A numeric `max_tool_calls` still caps all of a turn's delegations together. `Run.draw` takes `per_branch`, `Run.branch` names the top-level delegation, and `Run.tree_calls` starts at 0.
- `TREE_SPENT` reads "Tool-call budget for delegated work is exhausted", which fits both limits.
- `AppTty.write` writes to `sys.__stdout__`. A tool's `redirect_stdout` on another thread swaps `sys.stdout` for a buffer with no file descriptor, and the next frame raised `UnsupportedOperation: fileno`.
- Tests that checked wording, glyphs or restated constants were removed or replaced with behaviour tests.

## 0.2.67

- A sub-agent that a delegation sends to a named model now gets the tool list sized for that model. Every delegation was given the list sized for the session's default sub-agent model. A large model named beside a default with a window under 32k got that default's trimmed list, without the memory and web tools and with tool results clipped. A small model named beside a large default got the full list. Recorded on gpt-4.1-mini beside a 16k default, the sub-agent asked to read a page answered that it could not; with the fix it read the page and answered from it. `delegate_search` and `delegate_async` ask `get_tools_for(spec)` for the model they picked, `Agent._sub_plain` and `Agent._sub_tools` take that `spec`, and `delegate_many` takes `tools` as a callable from a backend's spec to its tools. A delegation that names no model still gets the default's list, and `get_tools` still works where `get_tools_for` is not given. A subclass that overrides `_sub_plain` must accept `spec=None` and pass it on.
- A sub-agent's own `delegate_search` caps the answers it reads at its own model's tool-result size, through `Agent._sub_budget(spec)`. It used the session's default sub-agent model's size. A large model's nested delegations were cut to a small default's 1,500 characters.

## 0.2.66

- `/learned` completes on Tab: its subcommands (`diff`, `accept`, `reject`, `compact`, `on`, `off`, `status`), then, after `diff`, `accept`, `reject` or `compact`, the ids Dhrona has pending. The ids are read at most once every `REF_TTL` seconds while typing.
- A slash command that answers with a git diff, such as `/learned diff ID`, is drawn by `diff_rich`, the fastpylight diff renderer tool results use. It printed as plain text.

## 0.2.65

- `Ui.kinds` maps each block's key to its kind ('tool', 'reply', 'note', 'step', ...), and `Ui.kind(blk)` reads it. `say` records the kind before teleprint's `put` runs, so an `on_change` observer such as the open transcript view sees it from the first repaint. A block put back under its key after a drop keeps its kind.
- Ramabana no longer sets `tag` on teleprint blocks, and no longer patches teleprint's `Block` class. 0.2.64's `Block.tag = None` and its `Ui._put` carry-over are gone. Code that read `blk.tag` on a Ramabana block reads `ui.kind(blk)`.

## 0.2.64

- A block printed while the transcript view is open during a turn no longer crashes the session with `AttributeError: 'Block' object has no attribute 'tag'`. teleprint's `Compositor.put` calls `on_change` before it returns the new block, and the open view's repaint read `tag` before Ramabana had set it. Every teleprint `Block` now starts with `tag = None`, and `Ui._put` keeps a block's `tag` when `put` returns a new block for a key that was dropped.
- Requires shalya 0.1.20. The Getting started pane, the now pane and `/watch` panes open beside the session's own pane, `$TMUX_PANE`, instead of beside whichever tmux pane is active.

## 0.2.63

- A session opens whatever the machine has. When the turn's model cannot run here and neither `--model` nor `$RAMABANA_MODEL` named it, `Agent.settle` moves it to `ready_turn()`: the first ready provider in `READY_ORDER`, a Claude Code, Codex or Copilot sign-in, then an Anthropic, OpenAI or Gemini key. Azure, Bedrock and custom endpoints are never picked. The session says which model it moved to and why. Building a `Routing` changes nothing, and `Routing.settled()` only names the move.
- A turn on Claude Code counts as unable to run when `claude auth status` reports `loggedIn: false`. It used to count as ready when the binary and SDK were installed, and the first turn then failed.
- A job whose default model cannot run here runs on the turn model and posts no note. A job someone gave a model of its own, directly or through `oneshot` (`Routing.chose`), keeps the old fallback order and says so once.
- An interactive session with no model that runs no longer exits. It opens on `welcome()`, warms no model, and in tmux opens a Getting started pane beside it: `getting_started()` as a checklist that redraws until a model is ready. On WSL the checklist says that Windows sign-ins, programs and variables do not reach Linux, and gives each missing tool's install line. A one-shot or piped run with nothing ready still prints `setup_guide()` and exits 1. `ramabana --doctor` prints the same checklist.
- `/login` lists the providers and which are ready. `/login NAME` runs the provider's own sign-in in this terminal (`claude auth login`, `codex login`, rishi's Copilot login), asks the endpoint questions for Azure, Bedrock and a custom endpoint, and asks for a missing key without echoing it. A turn that cannot run moves to the new provider, and a cold session then starts its model and code index. A turn that runs is left alone. `/model` switches it.
- Keys typed into `/login` go to `~/.config/ramabana/keys.env`, mode 0600, through `save_key`. `load_keys` reads it at startup for names the environment lacks, and refuses a file other users can read. A value written by hand as `!command` is a command whose output is the key, such as `!security find-generic-password -ws openai`. A typed value that starts with `!` is stored as text. The beat loads `keys.env` after `beat.env`.
- `/config` shows each setting and where it came from. `/config set KEY VALUE`, `/config reset` (the commented template, keeping `config.toml.bak`), `/config edit` (`$VISUAL`, `$EDITOR`, nano or vi in this terminal) and `/config reload` apply `[jobs]` to the running session through `Agent.apply_config`. A job this session set with `/model` keeps its model. A turn moves only to a model that runs here.
- `/model [JOB] NAME --save` switches and writes `[jobs]`.
- `ramabana setup` no longer asks which jobs a model serves. The new model becomes `[jobs] turn` when config.toml names no turn and no provider is ready. `--jobs` still names jobs. `config_reset` is the shared code behind `/config reset` and `ramabana config init --force`.
- `SETUP_HINT` names `/login` first. `/help`, the guide and tab completion know `/login` and `/config`.

## 0.2.62

- Requires teleprint 0.1.4 and pyghostty 0.1.3 (cli). Teleprint 0.1.4 names each block with a key and replaces `print_block`, `set_body`, `refresh_block` and `remove_block` with `put`, `extend` and `drop`, and `release` and `reanchor` with `async with borrow()`. Blocks are keyed by a counter in `Ui`, so a later block has a larger key. `blk.id` is now `blk.key`, and `Ui.toggle` takes a key, as teleprint's click and transcript view pass one.
- ctrl+z lends the terminal through `borrow`. Extended keys, mouse reports and bracketed paste are turned off while the shell has it and on again after `fg`. A second ctrl+z before the first resumes is ignored, so the terminal mode saved for the session cannot be raw mode.
- `borrow` stops and restarts Ramabana's own reader, which quits the session when the terminal hangs up. Teleprint's reader is not used.
- Teleprint 0.1.4's `start` turns on mouse reports. The mouse stays off until `/mouse on` or the transcript view, as before. Mouse reports now go through `set_modes`, so quitting from the transcript view also leaves the alternate screen.
- A tool call's fold is decided before it repaints, so the call never draws taller than it ends up. `put` folds a block once it passes `collapse_at`. That fold does not apply to calls or to blocks ctrl+o opened.
- Clicking a one-line call no longer fixes its fold. A diff shown in part renders whole in the transcript view and in part again after it.
- The transcript view rebuilds from teleprint's `on_change`. `NOTIFY_EVERY` is gone.
- `tests/test_azure.py` reads the Bedrock context window from fastllm's model table.

## 0.2.61

- Requires rishi 0.1.54 and uraiyadal 0.0.16. A hosted model's tool call cut off at the output limit, or with arguments that are not JSON, goes back to the model once, at a raised cap when cut off. A second failure fails the turn or the delegation with `ToolCallError` and the reason, for example "delegation failed after the sub-agent was asked: openai/gpt-5.6 failed (ToolCallError: openai/gpt-5.6's tool call was cut off at its 16384-token output limit; …)". It failed with a bare `JSONDecodeError`. A reply cut off while the model was still thinking is handled the same way.
- A hosted model with no `max_output_tokens` in config.toml now gets its own maximum output from fastllm's model table, or 16,000 tokens when the table does not know it. It got 4096, which a reasoning model's thinking could use up. The `max_output_tokens` key's documentation says so.

## 0.2.60

- Requires rishi 0.1.53, gheasy 0.0.14 and fossick 0.1.20 (search). `claude --version`, `ollama serve`, Git through gheasy's gateway, and Chrome and `gh_clone`'s git in fossick get `/dev/null` as standard input, so none of them can read keystrokes or set the session's terminal non-blocking.
- The git commands behind the code-index gate (`root_state`), `add_worktree` and the learned folder get `/dev/null` as standard input too.
- `hydrate_turns(cfg, turns)` is public. It gives rows read from `<cfg>`'s log their long tool results back from the details file, so a reader without an `Agent`, such as Dhrona, sees whole results. It was `_hydrate`.

## 0.2.59

- Requires rishi 0.1.52. A Gemini model routed as `gemini/<model>` no longer gets 404, and a Claude Code session that fails while connecting is tried once more, with a note in the session.
- Requires shalya 0.1.19. A command the agent runs gets `/dev/null` as standard input. It used to inherit the terminal. It could read keystrokes or set the terminal non-blocking, which froze the session before 0.2.58. `claude auth status`, the clipboard reader and the tmux log pane get `/dev/null` too.
- The turn log no longer keeps long tool results. A result over `RESUME_DETAIL` (600 characters) goes whole to `<history_name>-details/<session>.jsonl` in the config folder, and the row keeps its first 600 characters and a `details` reference. A resume replays only those 600 characters and reads the row alone. `session_turns` restores the whole results for a transcript or a branch editor. Results were about a quarter of a long-used `agent-history.jsonl`. Rows written before this keep their results inline and read as before. Nothing rewrites the log.
- The session index lists each session's byte ranges as `spans`, and `session_turns` reads only those. It used to read everything from a session's first turn to its last, which for a session resumed weeks later is most of the log. Index rows written before this, or past `MAX_SPANS` ranges, keep the first-to-last read.

## 0.2.58

- A session no longer freezes and then quits on the next key when its terminal was left non-blocking. A process that shares the terminal can set it non-blocking. A large frame then went out in part, and the next write failed with `EAGAIN`. `AppTty` counted that as a hangup, dropped every later write, and the next keypress ended the session with status 0, which closed the tmux session. Since 0.2.17. `AppTty.write` now writes the whole frame and waits up to `WRITE_WAIT` (5 seconds) for a full terminal to drain. Past that it drops the rest of the frame and the next tick repaints the screen. Only an error other than `EAGAIN` marks the terminal gone. `amain` sets the terminal blocking when it starts and again before it hands the terminal back.
- An exception in a key handler, or in a notice posted from another thread, shows as an error in the session, which carries on. asyncio's report still goes to `stderr.log`.

## 0.2.57

- `delegate_search` takes `model` and `effort`: one value for every question, or a list with one per question. A list of another length is refused before any sub-agent runs. `delegate_async` takes both too. `cloud_model` is still accepted as `model` and is no longer in the schema.
- A named model that is unknown or not set up fails its question with the setup message (`unknown model`, `needs KEY`, a missing runtime, and `ramabana setup`). No other model answers in its place. The other questions still run.
- Read-only questions on different cloud models run at once, across providers. Questions on the session's local engine run one after another in one worker. Writes run one at a time.
- Effort levels are `low`, `medium`, `high`, `xhigh` and `max`. A sub-agent's level comes from the delegation, then `/subagents effort`, then `$RAMABANA_SUBAGENT_EFFORT`, then `[subagents] effort`, then the model's default. A local model runs without one and its answer says so. A level the provider refuses is retried once without it, with a note.
- A turn's `reasoning_effort` reaches a Claude Code chat as its `effort`, per call. Nothing is left on the chat, so a turn without one runs at the session's level. `xhigh` and `max` are accepted.
- The tool channel is chosen in this order: `$RAMABANA_TOOL_CHANNEL`, a refusal this session, `/model tools` or `/subagents tools`, `[model."NAME"] tool_channel`, `runtime.tool_channel` or `subagents.tool_channel`, then the runtime's default. Claude Code's default stays `tags`. `native` sends its tools through rishi's in-process MCP server. `text` is accepted for `tags`. An MCP refusal moves the model to `tags` with one note.
- `/subagents model NAME|default`, `effort LEVEL|default` and `tools native|text|auto`, each with `--save` to write config.toml. Bare `/subagents` shows all of them. `/model tools native|text|auto [--save]` sets the turn's channel and keeps the conversation. Tab completes their arguments.
- `Agent.subagent_settings(model, effort, tools, save)` returns `{ok, model, effort, tools, note, unavailable, error}`. `/subagents` and `subagents_command` return the same dict, so a web route can send it unchanged.
- `/models` and `ramabana config models` show each model's tool channel and whether it takes an effort level.
- `ramabana config set KEY VALUE` writes one key, including `model."NAME".key`. config.toml takes `[subagents] effort`, `[subagents] tool_channel`, and `tool_channel` and `effort` in a `[model."NAME"]` table. `set_table` writes `[runtime]` and `[subagents]` under their own headers; they were written as model tables.
- Every parameter of Ramabana's own tools has a description: the delegation tools, `submit_result`, `set_plan`, `update_todo`, `remember`, `status`, the cart tools and the MCP `ask`.
- A per-turn effort level the model refuses is retried once without it. The chat keeps its own level, the note names the refused one, and that level is not sent again to that model. A refusal of the chat's own level drops it, as before.
- A local runtime (ollama, llama.cpp, MLX, LiteRT) always reports the native channel, since it takes no `tool_mode`.
- A `$RAMABANA_SUBAGENT_EFFORT` that is no level is ignored, and `/subagents` names it.
- `--save` writes only the setting its command changed. With no model, effort or tools change it writes nothing and says so.
- A sub-agent model named by its short name never runs on another model. Delegations that ask for one model at once share one backend.
- Requires rishi 0.1.51 and shalya 0.1.18.

## 0.2.56

- Recorded chats replay again. Since 0.2.53 a Claude chat is built with `on_stall`, a bound method whose repr holds a memory address, and `timeout_hint`, which names this machine's config path, and both went into the recording's key, so no key matched twice. `recorded()` now builds a `Recorder`, a `CachedChat` that leaves out of the key every option that is not plain data and the `UNKEYED` options (`timeout_hint`, `api_key`), and hands them to the live chat only. A test checks that two runs in two home folders give one key.
- The `03_agent` replays read a temporary config.toml and no `$RAMABANA_*` or `$LEELA_*` variable. Since 0.2.45 the effort a Claude turn asks for came from config.toml's `runtime.effort`, so a machine whose config set `effort = "medium"` keyed every turn differently from the recording.
- `delegate_search` is read-only by default, so several questions run at once. `writes=True` hands its sub-agents the session's write tools when the session allows them, and those run one after another. A read-only delegation's own sub-agents stay read-only.
- A sub-agent takes at most 80 steps by default, up from 60. A delegation that asks for fewer gets at least `SUB_MIN_STEPS` (20), not the session cap. The floor was `SUB_MAX_STEPS`, and every smaller request ran to the cap. The time limit stays 1800 seconds.
- The sub-agent briefing says a tool result that contradicts what the sub-agent just saw is likely a harness fault, to be confirmed once another way and named in its answer.
- The briefing's skill list points at `debugging` for diagnosing a failure or a tool that misbehaves, as it points at `coding_patterns` for code. The replayed `03_agent` turns list `debugging` too.
- Usage counts a Claude Code turn's thinking tokens under `reasoning`. It recorded 0. Requires rishi 0.1.50.
- The `[dhrona]` extra requires dhrona 0.1.14.
- The `03_agent` recordings are re-recorded.

## 0.2.55

- `ramabana-tick --install` warns when its `PATH` is launchd's default or cannot find `claude`, `git`, `git-lfs` (with the `node` a `#!/usr/bin/env node` claude needs) or the `ramabana-tick` it schedules, and names what is missing. It still installs.
- `beat_problems` reads the installed launcher and reports one written before the `PATH` was carried, a tool this shell finds that the launcher's `PATH` does not, a `ramabana-tick` that is gone, and a `beat.env` others can read, each with the command to run. A session's first beat note carries these lines, and `ramabana-tick --check` prints them and exits 1.
- Each beat loads keys from `~/.config/ramabana/beat.env` (python-dotenv), beside `config.toml`, for names its environment lacks. A file others can read is refused. Keys never go in the launcher.
- A beat stops itself after `--limit` seconds, six hours by default. SIGALRM, or the SIGTERM that launchd sends, raises `BeatTimeout` in the running fire. pobblebonk records it as that fire's failure, and the beat claims no further fire. A watchdog ends the process a minute later if no signal reaches the fire. `--install --limit N` writes the limit into the launcher.
- The `03_agent` tests read a temporary beat database, never `~/.pobblebonk/pob.db`. A real beat note no longer changes a recorded prompt.
- Requires pobblebonk 0.0.5 (`retry_after`) and python-dotenv.

## 0.2.54

- A fifth bundled skill, `debugging`, for diagnosing a failure, a tool that misbehaves, or Ramabana itself. It asks for the raw error before a hypothesis, a reproduction in the environment the failure ran in, and a read of the code before any claim about what it does or lacks, including the version that ran. A tool result that contradicts what the agent has seen, such as "no matches" for text it has just read, is treated as a harness fault: confirmed once by another route, recorded with `remember(component='tool')`, and named in the reply. It maps where Ramabana keeps its config, turn history, run logs, saved sub-agent answers, Claude Code transcripts, beat launcher, scheduler entry and Dhrona's nightly summaries, and how to check the `PATH` a scheduled beat runs on. Its test checks each path against the code that writes it.
- The replayed `03_agent` turns list only the four skills they were recorded with, so a new bundled skill no longer changes their system prompt.

## 0.2.53

- A Claude Code turn that sends nothing for 240 seconds is ended and tried once more, and the terminal shows a note saying so. Before, it waited 600 seconds in silence and then failed. Set the limit per model on this machine with `timeout` under `[model."NAME"]` in `~/.config/ramabana/config.toml`. If the retry goes silent too, the turn fails with an error that names the limit and that setting. Text already streamed is not repeated. The retry asks Claude Code to finish the reply. `Backend.notice` puts a status note on the run and passes it to `Backend.on_notice`, which the terminal sets. Requires rishi 0.1.49.
- `tab` after `@` completes files and folders. It searches the open folders through the host's own file walk, which respects `.gitignore`. A folder completes to `@dir/`, and further typing narrows inside it. A path starting `~/`, `/` or `../` lists from there when the host lets reads go outside the open folders. When it does not, the terminal says so instead of showing nothing. A path with spaces is quoted as `@"my notes/plan.md"`, and `file_refs` and `attach_refs` read the quoted form. In Python mode `@` stays a decorator.
- An `@folder` in a prompt attaches the folder's one-level listing, which reaches the model inside `<attached-files>`. Before, a folder was refused, and every `@path` failure was dropped silently. Attached files still go by path. A file outside the open folders attaches when the host's read policy allows it, and a credential path such as `.env` is never attached or offered. The terminal says what each `@path` attached or why it could not.

## 0.2.52

- The beat that `ramabana-tick --install` schedules runs on the `PATH` of the shell that installed it, and `--install` prints that `PATH`. launchd and cron start a job on `/usr/bin:/bin`. Dhrona's nightly batch found neither `claude` in `~/.local/bin` nor Homebrew's `git-lfs`. A round whose turn model runs on Claude Code could not start, and a replay of a repository that uses Git LFS could not check it out. Run `ramabana-tick --install` again to rewrite an installed launcher. Only `PATH` is carried. A key exported in a shell profile still does not reach the beat. Windows is unchanged.

## 0.2.51

- Requires rishi 0.1.48 and uraiyadal 0.0.15. A `<parameter>` element a model leaves outside any tool call is stripped from the reply text instead of shown.

## 0.2.50

- A line sent into a running turn reaches the model when the tool result it rides on is already as long as a result may be. The line was appended after the result, and the backend cut every result to `tool_max_len` from the end. A wide `delegate_search` or a clipped file view dropped the line unread. `_inboxed(mx=)` now shortens the body instead, saving the whole to a file the note names, and a line longer than half the cap arrives with its rest in a file too. Sub-agents get the same cap from their own backend.
- `delegate_search(writes=False)` hands its sub-agents read tools only, and several questions then run at once. Sub-agents may write by default, and sub-agents that may write run one after another. Every delegation of several questions therefore ran them in turn. Four read-only questions took four times as long. A read-only delegation's own sub-agents are read-only too, and `delegate_async(writes=True)` below one is refused.
- `ask(schema=)` works under the small profile. The small profile keeps only registry tools marked with `small_tool`, and `submit_result` was not marked. A typed result could never be handed back.
- Requires shalya 0.1.17, whose `grep` finds a folder named in `path_filter`, and rishi 0.1.47 with uraiyadal 0.0.14, whose tool schemas spell a `Literal` as an `enum` and read a pydantic model's fields.

## 0.2.49

- `generate_image` with no session folder saves under `media/` in the host's first open folder, not the process's working directory (shalya 0.1.16). In a desktop app the working directory is its data folder. Pictures used to be saved there instead of in the project.
- The terminal UI saves pictures the model returns itself under the agent's host folder when there is no session folder. It used to save them under the working directory.

## 0.2.48

- A `video` job. `video_route()` gives the model a host's `generate_video` asks, from `$RAMABANA_MODEL_VIDEO`, config.toml's `[jobs] video`, or `gemini/veo-3.0-generate-001` (`DFLT_VIDEO`): `{name, api, base_url, api_key, model}`, where `api` is `gemini` for Gemini's long-running Veo API or `openai` for an OpenAI-shaped `/videos` API, such as `sora-2` on OpenAI or an Azure deployment. A local model, a model fastllm knows returns no video, a missing key and a host with no video endpoint are each refused with what to set up. `video_route(name)` resolves one model by name, so a job started earlier is polled through the route it started on. `GOOGLE_API_KEY` serves a Gemini model when `GEMINI_API_KEY` is unset.
- config.toml accepts `[jobs] video`, `ramabana setup --jobs` accepts `video`, and `setup_guide` lists the video job beside the image job.

## 0.2.47

- Nothing is chosen for you. 0.2.46 moved every job onto Azure deployments, or another configured hosted model, when Claude Code and Codex were absent; that is gone, with `AZURE_OPENAI_DEPLOYMENTS` and `[azure] deployments` (config.toml now says what to do instead) and the `azure/...` rows `available_models` listed from them. A job falls back exactly as in 0.2.45. A deployment is used only where you name it: `azure/<deployment>`, or a `[model."NAME"]` table.
- When the turn's model cannot run here, the terminal prints `setup_guide()`: the providers Ramabana can use (`PROVIDERS`: OpenAI, Azure OpenAI, AWS Bedrock, Anthropic, Gemini, OpenRouter, Claude Code, Codex, Copilot, any OpenAI-compatible server, this machine), which are set up (`provider_ready`), and each job's model, where it was chosen (`job_source`) and whether it runs. A one-shot run prints it and exits 1; a session offers `ramabana setup`. `needs_setup(routing)` says why the turn cannot run. `Agent.start`'s note for a missing key or runtime ends with `SETUP_HINT`, as `reachable_hint` does.
- `ramabana setup` adds a provider: it asks which, writes a `[model."NAME"]` table for Azure, Bedrock or an OpenAI-compatible server, and the `[jobs]` it serves. Flags answer without a terminal. It never writes a key. `set_table` edits or adds one config.toml table and keeps every comment.
- AWS Bedrock works through its OpenAI-compatible Mantle endpoint, `https://bedrock-mantle.<region>.api.aws/v1`, with a Bedrock API key in `AWS_BEARER_TOKEN_BEDROCK`; windows come from fastllm's `bedrock_mantle` table. Claude on Bedrock and Bedrock's native Converse API are not supported. fastllm has no SigV4 signing, AWS profiles or Converse format.
- `generate_image` draws with the `image` job: `[jobs] image`, `$RAMABANA_MODEL_IMAGE`, or `openai/gpt-image-1` by default (`image_route`). An Azure deployment of `gpt-image-1` works through a `[model."NAME"]` table, and nothing goes to api.openai.com by name. Without an image model the tool is left out, and `setup_guide` says what it lacks. A turn on a custom endpoint no longer tries to draw itself through OpenAI. Requires shalya 0.1.15.
- `openrouter/<vendor>/<model>` checks `OPENROUTER_API_KEY`.

## 0.2.46

- Azure OpenAI is a route of its own. `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_API_KEY` set it up; `azure/<deployment>` names a deployment anywhere a model is named, and goes to the resource's v1 API through the Responses API, with no `api-version`. `AZURE_OPENAI_DEPLOYMENTS`, comma-separated, lists the deployments to offer and route to. config.toml's `[azure]` table can hold `endpoint`, `deployments` and `api_key_env` instead; the env vars beat it, and the key never goes in the file. Any shape of endpoint pasted from the portal is reduced to the v1 base (`azure_base`).
- Azure shows in `auth_status()['azure']`, in `available_models` as `azure/<deployment>` rows, and in `model_note` as `Azure OpenAI`. A deployment named for a model fastllm knows gets that model's window and briefing. Any other name runs with 128k and a note naming the `[model."azure/NAME"]` entry that corrects it. A missing endpoint or key is named, as a missing API key is.
- With no Claude Code and no Codex login, the defaults no longer fail. When a hosted model is configured here, `Routing` moves each job still on a default that cannot run to it, with one note: the chosen turn when it is hosted, else the first of `remote_models()`, and the first name holding `mini` or `nano` for the cheap jobs. A job you chose never moves, and a moved job still follows a local turn named later. `alternatives` tries the configured hosted models before `DFLT_FALLBACK`. Azure set up with no deployment named says how to name one.
- config.toml can define a model. A `[model."NAME"]` table with `model_id` registers `NAME` with `runtime`, `base_url`, `api_key_env`, `api_name`, `vendor_name` and `ctx` (another name for `max_input_tokens`). On an Azure host `api_name` defaults to `openai` and `api_key_env` to `AZURE_OPENAI_API_KEY`. A table that names a built-in model, an unknown or missing runtime, or API settings without `model_id` is ignored with one warning, which `model_problems()` and `Agent.problems` repeat.
- The terminal session, `ramabana-mcp`, `ramabana-acp` and anything else that builds an `Agent` load the saved aliases and config.toml's definitions on first use. `[jobs] turn = "az-big"` raised "unknown model" from the CLI, which never loaded an alias. `sync_models()` registers both again whenever either file changes; `resolve`, `available_models` and `Routing` call it. A name defined in both is config.toml's: `load_models` skips it and `save_model` refuses it. `use_aliases(path)` points the alias calls that name no file at an application's own file.
- A chat a host builds through `lend_model` keeps the model's `base_url`, key and `api_name`. It used to get the model id alone, so a vault or MCP chat on a custom endpoint went to the vendor's default URL.
- Requires rishi 0.1.46, which sends `max_completion_tokens` on Azure's chat-completions route.

## 0.2.45

- A message too large for the window goes out cut, not refused. A huge paste, a message with more pictures than fit, or a giant tool result in the newest exchange is cut to its head and its end around a note: `…[N characters omitted; full text at <path>; read it in pieces with view_file(path, start=N)]`. The whole is written to `<cfg>/runs/<session>/full/`, mode 0600, and the folder is opened to the read tools for reading when they cannot reach it. Of many pictures, the newest that fit stay and the rest are saved and named by path. The log keeps the prompt as typed. A message or newest exchange larger than half the room is cut before anything else, so a short conversation is not compacted for one paste. The reminders added to the end of a prompt are kept whole, and a prompt holding a notebook is left to the notebook's own cutting first.
- A trimmed tool result is written to a file first, and its note names the file.
- Compaction never sends the summarizer more than its window. A history too large for one request is split into runs that fit, and each run updates the summary of the ones before it (`fold_summary`, `transcript_runs`). A failed or empty step leaves the conversation alone, as before.
- A turn that does not fit compacts even with automatic compaction off.
- The first turn after a resume is measured before the chat starts, and a hosted chat that has not reported a step counts its briefing, tools and messages.
- `ContextFull` is left for a briefing and tools that alone overflow the window. Its advice comes from the host: `Agent(fresh_hint=)`, with `{session}` for the session id. The terminal session passes `CLI_FRESH`, which says to quit and `ramabana --resume <id>`. Without a hint the advice is `FRESH_HINT`, which names no command, for Leela, ACP and MCP.
- `~/.config/ramabana/config.toml` holds this machine's settings, one hand-edited file that every Ramabana on the machine reads, whatever its `--cfg`; an app that embeds Ramabana reads the same file and never writes its own folder for it. `$RAMABANA_CONFIG` names another file. A flag beats an env var, an env var beats the file, and the file beats the built-in default. Keys: `learning`; `[jobs]` `turn`, `oneshot`, `inline`, `completion`, `classify`, `summary`, `subagent`; `[window]` `margin` (was only `EST_MARGIN`), `image_tokens` (`IMG_TOKENS`), `reserve` (`RESERVE`), `keep_recent` (`KEEP_RECENT`), `local_ctx`; `[compaction]` `auto`, `strategy`; `[runtime]` `effort`, `tool_channel`, `litert_backend`; `[cli]` `approve`, `theme`, `tmux`, `pane`, `profile`, `max_tool_calls`, `max_steps`. A `[model."NAME"]` table corrects fastllm's numbers for one model: `max_input_tokens` replaces the window the guard sizes turns against, `max_output_tokens` becomes the chat's reply cap, and `supports_images` answers `accepts(spec, 'image')`. The route name wins over the model id.
- `ramabana config init` writes the file with every key commented out beside its default and refuses to replace one unless given `--force`, which keeps `config.toml.bak`. `ramabana config show` prints each value in effect and whether it came from an env var, the file or the default, with fastllm's window beside a corrected one. `ramabana config path` prints where the file is.
- An entry config.toml cannot use, a key nobody knows with the nearest one it might mean, a value of the wrong type or outside its choices, or a file that is not TOML, takes its default and gives one warning, which `Agent.problems` and `config show` repeat. Nothing raises.
- `learning` moves from each config folder's `settings.json` to config.toml, one switch per machine. `enabled(cfg)` reads a value only `<cfg>/settings.json` holds and writes it into config.toml the first time, and never writes `settings.json`. `set_enabled` rewrites the one `learning` line and keeps every comment. A config.toml that is not valid TOML is never rewritten: `set_enabled` raises `ValueError` saying so, and `/learned on|off` returns that message.

## 0.2.44

- A turn after a compaction no longer fails with "input is too large". A hosted chat's `token_count` is the window its last step reported, and rewriting the history never changed it. When a turn's steps ended past the window, the next turn compacted, `fits` still read the old count, and the turn raised. Every retry compacted again and raised again. After `replace_hist` or `restore_hist`, `used_tokens` now gives `window_tokens`, an estimate of the briefing, the tool schemas and every message, until the chat reports a new count. The guard is unchanged since 0.2.35. The window exposed the fault: fastllm 0.0.65 gives `codex/gpt-6.1-sol` 371,000 tokens where fastllm 0.0.45 gave 922,000, and a conversation of about 370,000 tokens now reaches the line.
- A resumed conversation is counted before its first turn goes out. It used to count as 0 until a step reported, so a long one was sent whole without compaction.
- A prompt with a pasted picture is logged as text, with `[image]` where the picture was. The log used to keep the repr of the picture's bytes, about 560,000 characters for one screenshot, and a resume replayed it to the model as text, about 300,000 tokens on every step. `turn_prompt` reads such rows from older logs as text. Those sessions resume small. `prompt_text` gives the text form.
- A turn that does not fit first trims the oldest tool results and then the oldest pictures, then compacts. One that still does not fit fails with a message that gives the sizes and the model's window and says how to start fresh or resume later, not a `ValueError`. `ContextFull` is that failure.
- A picture is charged 1,600 tokens (`IMG_TOKENS`, was 1,024), and the pending message 15% over its estimate (`EST_MARGIN`).
- Learning has one persistent switch per config folder, `learning` in `<cfg>/settings.json`. `/learned on|off|status`, `ramabana-learned on|off|status`, and `ramabana.learned.enabled(cfg)` and `set_enabled(cfg, on)` read and set it. Off leaves the learned `AGENTS.md` and learned skills out of the briefing, drops the rule to record lessons, keeps `remember` to plain notes, returns no lessons from `Agent.lessons()`, writes no `start.json`, and makes Dhrona's nightly schedule return "learning is off" without touching the learned folder. It is on by default. `Agent.learning` says whether it is on.

## 0.2.43

- A model whose runtime is missing on this machine no longer raises in `resolve`. On a machine without Claude Code, building an `Agent`, reading `agent.model`, listing sessions and `set_model` raised for the default `claude-opus-5-5`. `resolve` now returns the spec with `missing` set: which binary or package is absent and how to get it, for example "claude runtime is unavailable (`claude` is not on PATH); install Claude Code ...". A missing API key already worked this way.
- `Agent.start` reports a missing runtime as a failed turn, recorded like any other. The note names a model that does run here, taken from `available_models`. The turn model is never switched. Jobs other than the turn fall back as their routing already says. `missing_runtime(spec)` asks the same question live, so a runtime installed mid-session is picked up on the next turn. `model_note` shows the reason.
- `resume_session` keeps the current model when the conversation's model cannot run here, and says so. A lent factory and a delegated fan-out skip a model whose runtime is missing.
- A one-shot `ramabana -p` on a missing runtime prints the reason and exits 1, as it does for a missing key, where it used to exit 2 before the turn.

## 0.2.42

- The `dhrona` extra requires dhrona 0.1.13. Under 0.1.12, about one compaction in ten that folded in a candidate lost the candidate's id to scrubbing. Accepting the compaction then left that candidate pending.

## 0.2.41

- An accept refused for size returns the would-be `length` and names `/learned compact ID`. `compact(folder, id)` and `/learned compact ID` fold that candidate into the compaction, and accepting the compaction accepts the candidate and drops its branch.
- After an accept moves HEAD, `restack` moves every other pending candidate onto it where it picks cleanly. `accept` returns `moved` and `stale` ids, and `/learned accept` names them. `pending` gives each candidate a `stale` reason, or None, and `/learned` shows it. A candidate that no longer applies is visible before anyone tries it. `accept` of such a candidate returns the same reason (`STALE`).
- `pending` sorts by when Dhrona proposed a candidate, and `at` is that time. Moving a candidate keeps its place.
- The `dhrona` extra requires dhrona 0.1.12, which has `compact_learned(onto=)`.

## 0.2.40

- `ramabana.learned.compact(folder)` asks Dhrona for a shorter learned `AGENTS.md` and returns `{ok, id, before, after}`, where `before` and `after` are character counts, or `{ok: False, error}`. Dhrona's editor model merges and shortens the paragraphs Dhrona proposed and keeps every paragraph a person wrote byte for byte. The result waits as one more pending candidate. `diff`, `accept` and `reject` act on it. Without Dhrona it returns an error naming the `dhrona` extra.
- `/learned compact` in a session and `ramabana-learned compact` from a shell run it. The help and the guide name it.
- An accept refused past the 2,000 characters Dhrona allows now says to reject the candidate, run `/learned compact`, or trim `AGENTS.md` and commit that first.
- The `dhrona` extra requires dhrona 0.1.11, which has `compact_learned`.

## 0.2.39

- `/learned` reviews what Dhrona proposes from inside a session: `/learned` lists, and `/learned diff|accept|reject ID` acts on one. Tab completion offers it, and the help and guide name it. `learned_command` is the text form `/learned` and `ramabana-learned` share.
- `accept` refuses a candidate that would take the learned `AGENTS.md` past `LEARNED_MAX`, the 2,000 characters Dhrona allows, and leaves HEAD as it was. Reject it, or trim `AGENTS.md` and commit that first.
- The `dhrona` extra requires dhrona 0.1.10, whose kept candidates wait on `pending/` branches.

## 0.2.38

- `ramabana.learned` is the review queue for `<cfg>/learned`. Dhrona 0.1.10 commits each candidate on a `pending/<id>` branch and leaves the folder's files, which the briefing and skill discovery read, alone. `pending(folder)` lists the candidates, and `diff`, `accept` and `reject` act on one and return `{ok, id, ...}`, with `error` when `ok` is False. `accept` picks the candidate in a throwaway worktree. A conflict never reaches the files a session briefs from. `accept` and `reject` refuse while a Dhrona batch holds the folder's lock. `diff` takes no lock. `learned_folder(cfg)` names the folder.
- `ramabana-learned` runs the same from a terminal: `ramabana-learned` lists, and `ramabana-learned diff|accept|reject ID` acts on one.
- `Agent.lessons()` returns this project's lessons as dicts of `lesson`, `cue`, `component`, `evidence` and `confidence`, read with shalya's `lessons` from the vault or the memory file alike. Requires shalya 0.1.14.

## 0.2.37

- `local_window` reads a llama model through rishi's public `llama.get_model`. Requires rishi 0.1.45.
- Requires shalya 0.1.13; the image tests replace its public `post_image`.

## 0.2.36

- A session that already has turns writes no `start.json`. A session resumed from before that file existed used to write the state at the resume as the state it began from, and Dhrona replayed its first turn from the wrong commit. `start.json` is written atomically.
- A learned skill that takes an inlined skill's name, such as `exhash`, is clipped in the briefing to the cap the learned `AGENTS.md` has, `MAX_CONTEXT_FILE`. `read_skill` still returns it whole.
- `demo_agent` briefs the same on every machine.
- Requires shalya 0.1.12 and imports its public `mod_skill`, `describe`, `fuse` and `post_responses` instead of the `_` names.

## 0.2.35

- `recorded()` treats every runtime as available while it replays. A page that replays Claude's answers now runs on a machine without Claude Code, such as the docs build.
- A `WorkspaceHost` without a vault drops `mk_chat`, `pii` and `pii_ner` again, so `Agent.lend_model` leaves it alone. The line that did this had ended up after a `return` and never ran.
- `dev` is an extra, and the `dev` dependency group installs it. CI and the docs build install `.[dev]`, which installed nothing before. `dev` requires nbdev 3.3.25, which leaves modules with no exports out of `_modidx.py`, as CI's nbdev does.
- The routing examples in `core` show the current policy's output.

## 0.2.34

- `ramabana-tick --install` quotes the tick's path in the launcher it writes. uv installs tools under `~/Library/Application Support` on macOS, and the unquoted path split at the space. An installed beat never ran. Run `ramabana-tick --install` again to rewrite an existing launcher.
- The `Agent.beat` example checks a machine with no beat against an empty beat home. It read the real `~/.pobblebonk/pob.db` before, and failed on a machine with a beat installed.

## 0.2.33

- `ramabana-tick` runs the callbacks installed packages register through the `ramabana.ticks` entry-point group. Each entry point's name is a pobblebonk schedule, and its value is the callback a fire of that schedule runs. The beat imports the package only when its schedule fires. An `on_tick` callback with the same name replaces the entry point's.
- The `dhrona` extra requires dhrona 0.1.8. Its `nightly` runs a Dhrona batch when the `dhrona` schedule fires, within the schedule's `budget` in dollars.
- Requires rishi 0.1.43, which stops a Claude reply at its first tool call. A model that wrote a call and kept going no longer has its invented results passed on as the answer.

## 0.2.32

- Skills in `<cfg>/learned/skills` load through shalya's `discover(learned=)`. They override the packaged skills and lose to every skill folder a person writes. `--no-learned` and `Agent(learned=False)` leave them out with the rest of the folder.
- `remember` without a vault takes `cue`, `component`, `evidence` and `confidence`, as shalya's does, and checks them with shalya's `lesson_text`. A lesson is one ` | `-separated line in the project's `MEMORY.md`. A note without them is stored as before. The Claude notes ask for these fields when a turn shows a mistake with a reusable correction.
- A model failure the backend caught is a failed turn. `Backend.send` and `stream` keep it in `turn_error`, and the history row and the run are `failed`, with the error, instead of `complete` with an empty error.
- Requires shalya 0.1.9, whose `search_code` hints name only the tools that reach a hit, and koshas 0.1.10 in the `search` extra, whose quiet `sync` keeps `--json` output valid.

## 0.2.31

- `ramabana.hl.diff_html(s, lang=None)` returns each line of a unified diff as escaped HTML spans, or `None` for a line outside a hunk body. A span carries its scope and every dotted prefix of it as classes, such as `hl-function hl-function-builtin`, and `fastpylight.theme_css` styles those classes. Leela colours its diff views with it.
- `hl_toks`, `hunk_toks` and `diff_toks` return the same tokens as data, in character offsets. A token that crosses a line break is cut at it. Each side of a hunk is tokenized whole, so a string spanning lines keeps its scope. `toks_html` renders one line's tokens. `diff_rich` colours from `hunk_toks`, and its output is unchanged.
- `<cfg>/learned/AGENTS.md` goes in the briefing after the built-in rules and before the project instructions. `--no-learned` and `Agent(learned=False)` leave it out.
- The first turn of a session writes each open folder's repository, branch, HEAD and modified tracked files to `<cfg>/runs/<session>/start.json`. A resumed session keeps the file it began with.

## 0.2.30

- Compaction moves past a summary model that fails. It summarises through the summary job's routes, as `Agent.oneshot` does: a cloud model that fails or answers nothing is set aside, and the next route is tried, the turn model among them. Before, a failing summary model, such as one an API key has no access to, left the conversation uncompacted.
- Compaction never hands a route a prompt larger than its window. A backend trims such a prompt, and a summary of the rest would replace the whole history. The compactor retries with a smaller prompt, and when none fits, the history is left whole and the note names the window.
- A summary model that cannot start leaves compaction on the turn model, as before.
- When every route fails, the compaction note names the newest failure among the summary job's routes, such as `compaction failed (... model_not_found ...)`. It said the summarizer returned nothing.
- `Agent.oneshot(fits=)` takes a check on each route's backend. A route it refuses ends the search with `''` and is not set aside.

## 0.2.29

- A line that starts with `!` in agent mode runs as a shell command in the first open folder. Its output and exit state print in the transcript and are never sent to the model. It runs without an approval, in every approval and plan mode. It reads no input, so it cannot answer a password prompt. Its output prints when it finishes. In python mode a `!` line is Python.
- `ctrl+c` sends `SIGINT` to a running `!` command, and the next `ctrl+c` sends `SIGKILL`. A command that a signal ended prints `stopped`. Quitting kills a command that is still running. A `!` line typed during a turn waits behind it.
- An interactive session's briefing tells the model that the user can run commands with `!`. `main` adds `SHELL_NOTE` to `agent.extra_sp`. A `-p` run does not get it.
- Diff and code highlighting moved to the new `ramabana.hl`. Its functions take the palette and the Lumis theme: `hl_text(code, lang, theme)`, `diff_rich(s, palette, theme)`, `scope_style(scope, theme)` and `diff_lang(path)`. `ramabana.cli` keeps `hl_text(code, lang)` and `diff_rich(s)`, and adds `hl_theme(name)`. `cli.scope_style` is removed.
- A notebook's diff, or one cell's as `nb.ipynb#id`, is highlighted as Python, in the transcript and in the side pane.
- The side pane draws an open file's diff with `hl.diff_rich`: the code highlighted by its language, and added and removed lines tinted.

## 0.2.28

The rest of `docs/plans/2026-10-12-embedding-host.md`: items 9 to 14.

- `agent.events_to(path, max_bytes=)` appends one JSON line per event to `path`. Events are a call starting and finishing, an ask raised and answered, a plan change, a turn starting and ending with its state and usage, and steering delivered. Each line is flushed when written. A file past `max_bytes` is renamed to `<name>.1` and a new file is started. The file is created readable by this user only. The terminal's and ACP's own listeners do not replace it.
- `mk_agent(python='off')` withholds `run_python` and the other Python tools. `python=` set to a Dhrishti URL runs them in that kernel. The default `'host'` runs them in this process.
- `Agent(global_skills=False)` reads no skills from `~/.agents/skills`. `Agent(extra_sp=)` adds text after the briefing. `sp=` still replaces the briefing. `mk_agent(rules_path=)` keeps a job's allow and deny rules in their own file.
- `agent.queue(prompt)` holds a prompt and returns the queue length. `agent.run_queued()` runs the held prompts in order and returns their `TurnResult`s. Steering that arrived after a turn's last tool call joins the next turn.
- `Agent(keep_conversation=True)` saves the turn model's whole conversation after each turn in `runs/<session>/hist.json`, with its backend and model. `resume_session(id, full=True)` restores it with every tool result whole. A saved conversation is used only for the same backend and model. Otherwise the session is replayed as text. A tool call left without its result is trimmed off. The default saves nothing.
- A stop that leaves its backend running hands the conversation to the next turn's backend.
- `host.add_worktree(repo, branch, path=None, readonly=False)` creates a git worktree of `repo` on `branch` and opens it as a root. An existing branch is checked out. A missing branch is created from the checked-out commit. The default path is `<repo>-<branch>` beside `repo`.
- `ramabana.control.Control(agent).start()` listens on a Unix socket, `runs/<session>/control.sock`, readable by this user only. A path too long for a socket moves to the temp folder. `control_call(path, method, **params)` sends one request. The methods are `prompt`, `steer`, `cancel`, `asks`, `answer`, `status` and `events`. A prompt sent during a turn is queued. `cancel` drops the queued prompts and returns their number in `dropped`. `events(offset=)` returns whole lines from `offset` and sets `rotated` when the file rolled over. A turn that raises is recorded in `status` as `failed`. `start` refuses a path another runner listens on and a path that is not a socket. A socket a crashed runner left is replaced.
- `examples/embed_host.py` runs one job end to end: a policy, a typed result, an ask answered by id, the event file and a read-only reference folder.

## 0.2.27

What a long-running host needs to embed an agent, from `docs/plans/2026-10-12-embedding-host.md`.

- `Approvals` holds every waiting ask. `answer(id, ok)` resolves any of them once, and each answer reaches `on_answer`. `waiting` lists them oldest first, and `pending` is the oldest. `cancel_all(run=)` refuses the asks of that run and the runs it started.
- `Approvals(no_listener='wait')` holds an ask until a page listens, and that page is shown the asks already waiting. `on_timeout='allow'` lets an unanswered ask through. `mk_agent` takes `timeout`, `no_listener` and `on_timeout`.
- `Approvals(policy=fn)` is consulted before rules and modes. `fn(name, args)` returns `'allow'`, `'deny'`, `'ask'` or `None`. A policy that raises asks. An ask the policy or the loop guard put to a person is not allowed by a timeout, and `/approve` does not settle a policy's ask. `registry.approval(fn)` sets the policy.
- An ask put to a person is an activity row of kind `ask` and state `awaiting`, with its `ask_id`, before its call runs. Its answer finishes the row. The terminal and ACP show their own prompt instead.
- `agent.ask(prompt, schema=...)` returns a `TurnResult` whose `result` is validated against a pydantic type or a JSON schema dict. The model hands it back through a `submit_result` tool that lasts for the call. `result=True` returns a `TurnResult` without a schema. `strict=True` raises `TurnFailed` for a turn that did not complete and `ResultMissing` for a schema never filled.
- A turn in a session another live process holds raises `SessionBusy` before anything is written. `Agent(session_id=)` names the session. History lines appended by two processes at once stay whole.
- `Agent(max_cost=, max_tokens=, session_max_cost=, session_max_tokens=)` stop a turn after the model step that passes them. The turn is recorded with state `budget`.
- `mk_agent(read_roots=)` opens folders that the read tools search and no write touches, and the briefing names them. Requires shalya 0.1.7.

## 0.2.26

- The plan checklist no longer covers the end of the transcript. It heads the live tail and pushes the transcript up. It takes only the rows the screen can spare and always leaves 4 transcript rows. It steps aside while a menu, slash completion or the browsing view is open. Ctrl+T still hides it.
- A paragraph after a list that sits directly under its lead line is drawn as its own paragraph. It was drawn as a continuation of the list's last item. A block quote or table under a lead line is fixed the same way.

## 0.2.25

- A session resumed with `--resume` or `/resume` draws its last 10 turns: each request, the lines sent during it, and its reply. A stopped or cut-off turn gets a note. A longer session gets a note with the number of turns not shown.
- Session titles are whole. The index kept each session's first prompt cut to 72 characters, wrapper included, so titles stopped mid-word. It now keeps the title, and the first listing after an upgrade rebuilds the index from the log once.
- Titles the summary model wrote lose `**bold**`, a `Title:` or `Conversation Title:` label, quotes and anything after a spaced `---`. A title the person set is shown as set.

## 0.2.24

- A bare `ramabana --resume` lists the sessions that ran in the current folders, newest first, with their age, turn count and title. Enter resumes the newest, a number picks one, and `n` starts a new session. A session another process holds is marked `(in use)` and cannot be picked. `--all-folders` lists every folder's sessions. Without a terminal, a bare `--resume` means `latest`.
- `/sessions` lists the current folders' sessions, and `/sessions all` lists every folder's.
- A session is saved with a title from its first request: its first sentence, at most 80 characters, without the harness's reminder and notebook blocks. A session recovered after a crash gets a title too. A session records every folder it runs in. A session saved before 0.2.24 has no folder record, and appears only under `--all-folders` and `/sessions all` until it is resumed in a folder.
- Summaries, inline edits and other one-shot jobs run on `gpt-6-luna` through a Codex login. `gpt-6.1-luna` through `OPENAI_API_KEY` returned empty answers. Without a Codex login, these jobs move to another cloud model, and the note says to run `codex login`.
- A cloud model whose one-shot answer fails or is empty is set aside for five minutes, and its jobs move to the next route. A model busy with another call is not set aside. Naming a model with `/model` clears it.
- With no cloud route left, a job runs on `gemma-e4b` on the device. The turn never falls back. The chat says once where a model's jobs went.

## 0.2.23

- A turn cut off by a crash can be resumed. The turn in flight is kept in `runs/<session>/turn.json` until its row is written. Listing sessions turns one whose process died into an `interrupted` row with its prompt, and `/resume` replays it with a note. A session that crashed in its first turn now appears in `/sessions`.
- A session in use is never resumed by another process. A session is held through `runs/<session>/owner.lock`. `--resume latest` skips a session another live process holds and prefers sessions from the current folders. `/resume ID` on a held session is refused and names the process holding it. Two processes no longer share one run folder. The side pane no longer flickers between them.
- Each session's stderr goes to `stderr.log` in its own run folder, appended rather than truncated, and `faulthandler` writes a hard crash's stack there.
- When the same call returns the same result three times in a row, the result carries a note to use it, change the arguments or answer.
- The status bar says `ready` once startup finishes. It kept a frozen `working` and a `thinking` line until a key arrived.

## 0.2.22

- `view_file` on a generated module returns its text again. The generated-file guard applies only to writes.
- A call an extension rewrites in `before_tool` meets the guards again. A refused rewrite is not put to the user for approval.
- The come-up-for-air reminder no longer reaches sub-agents, which report to their caller. A steering message restarts its count.
- Plan mode and `--readonly` reach sub-agents and folder-watch reviewers, which get the same read-only view as the turn model. A delegation already running keeps the tools it started with. The plan-mode briefing says what stays: the reading tools and the plan tools.
- A command typed while a turn runs, such as `/python`, comes back to the composer on Alt+Up or Ctrl+C.
- A chunk the model thread posts after the event loop closes is dropped instead of raising.
- Sub-agents are briefed with their model family's notes and the characters the caller reads of their answer.
- A long missing-skill note takes at most a quarter of a delegation's budget, and a `delegate_result` page always moves forward.
- Requires shalya 0.1.6, where clipped JSON and lines stay within their budget.

## 0.2.21

- Tool results scale with the model's window. `tool_max_len=None`, now the default, gives a quarter of the window's tokens in characters, at least 6000 and at most 32000. A small window still gets less. Requires shalya 0.1.5, where a clipped result fits its budget with its note, keeps the rest in a file `view_file` can read, and a git report stays JSON.
- Delegation results fit the model's budget, notes included. Each question gets its own share, a clipped answer is saved to a file named in the note, and `delegate_result(run_id, offset=)` reads a long answer in pages.
- The briefing is lighter. `coding_patterns` is no longer inlined, and the catalogue points to it. Each skill is one clipped line. Claude, GPT and Gemini turns each get notes for their family.
- rishi's per-message tool reminder and its summary-less sliding window are removed from turn chats. Compaction stays with `Compactor`.
- Only a runtime that hides text between tool calls is told that such text may not reach the user.
- `/resume` replays a cancelled turn: its prompt, its partial reply and what was sent mid-turn, with a note that it was interrupted. An abandoned stream is still left out.
- Typed text is never lost. Ctrl+C and Alt+Up return unread steering, queued lines and the draft to the composer. A refused command keeps its text. Each queued line has its own row.
- A steered line gets a check mark once the model has read it.
- Narration between tool calls reaches the notebook log. A cancelled turn logs its partial reply, and the chunk in hand when a cancel lands is drawn and logged.
- Alt+O folds or opens every tool block in the transcript, including turns already scrolled away.
- One-character prompts: `.` continues the agreed task, `;` restates the last answer more simply, and `,` lists what the user needs to answer next.
- `run_shell` refuses `| head`, `| tail`, `|&` into either, and `2>&1`, inside `sh -c` too. A write to an nbdev-generated module is refused, and the refusal names the notebook to edit.
- After 8 tool calls with fewer than 100 characters said before each, the next tool result reminds the model to tell the user where the work is, quoting their request.
- Plan mode: `/planmode on|off`, or Shift+Tab after auto. It withholds every tool that acts, asks the model for a numbered plan and re-briefs a running model in place. Leaving it sets approvals to ask.

## 0.2.20

- No local model loads unless one is chosen. With a vault open, rebuilding its entity graph used vishalakshi's default chat, a local Gemma 4 on LiteRT. A session on cloud models loaded it mid-turn. The graph is built only when `graph_chat` is given or `$VISHALAKSHI_MODEL` names a model. Topic nodes need no model and still update.

## 0.2.19

- Default turns use `claude-opus-5-5` and sub-agents use `claude-sonnet-5-5`. Classification and completion use `claude-haiku-5-5`. Oneshot, inline and summary jobs use `gpt-6.1-luna`.
- Gemma is no longer the suggested local model. Explicitly selected local models remain supported.
- Sub-agents may write by default behind the session's approval gate. `--no-subagent-writes` or `/subagents off` makes them read-only.
- Sub-agents default to 60 steps, a 1800-second timeout and two levels of nesting.

## 0.2.18

- A line with attachments steers the running turn instead of waiting in the queue. Each attachment goes by path for the model to read with `view_file`. A tool result carries no picture.
- Enter on an empty line hands the queued line to the running turn. The queued row says so.

## 0.2.17

- A session whose terminal closed exits cleanly. `RealTty.read` spun at 100% CPU on a hung-up terminal, and teleprint's TERM/HUP handler raised while restoring a dead terminal. The process ignored a polite stop. The CLI's `AppTty` stops reading at the end of input, a closed terminal or TERM/HUP quits through the teardown, and the teardown stops background shells and kernels.
- Background commands no longer open tmux panes. `run_shell_bg` logs to a file with its input detached from the terminal. Several at once used to stack panes under the chat until it disappeared.
- In the side pane, a background shell opens to its full command and its last lines, or "(no output yet)". `p` on one opens a tmux pane following its log (`less +F`, closed with `q`). The pane's last line lists the keys.

## 0.2.16

- Sub-agents report back. Three causes, fixed together:
  - A delegation gets at least `SUB_MAX_STEPS`, within the session's cap. A turn model asking for five or eight steps left its sub-agent out of budget before it could report.
  - The sub-agent briefing says the budget notice and the request to answer come from the harness. A Claude sub-agent took them for injected text, refused them, and ended with nothing.
  - Requires rishi 0.1.41 and uraiyadal 0.0.12. A Claude sub-agent that wrote its calls in its own `<invoke>` dialect had them dropped and returned only its opening line. Those are read now, and a call nothing can read is asked for again.

## 0.2.15

- Background rows in the pane open: a `run_shell_bg` command to its last `SHELL_LINES` lines of output, fetched no more often than its state already was; a folder watch to its pattern, review count and last review (`FolderWatch.last_review`); a background delegation to its sub-agent's calls and answer.

## 0.2.14

- One message is one note, however many calls it makes. Each of a batch's calls starts through `Run.on_call`, and the later ones fell back to the same message. The pane showed it once per call.

## 0.2.13

- Library output no longer corrupts the terminal. While the TUI runs, Python's `sys.stderr` goes to `<cfg>/stderr.log`: kosha's index sync drew a tqdm bar from a background thread, and every update scrolled the screen under teleprint's frames, leaving a copy of the status bar behind each time. A session that wrote there says so on exit.
- The pane keeps the model's running notes: what it said before each call, whole and timestamped (`Run.notes`, up to `NOTE_KEEP`). Each note folds to its time and first line and opens to every word; the newest starts open.

## 0.2.12

- A turn's whole answer reaches the terminal. `run_turn` stopped reading once the run finished and dropped what was still queued. On the Claude backend, which hands over a step's text in one chunk, that was the entire answer.
- Narration stays on screen: what a model writes before a call is kept as a `┆` step above the call instead of being removed. Ctrl-O and alt+1..9 still fold only the calls, and `/copy` copies the answer.
- No keyword routing. The model picks its tools, including when to search the web, and only a tool named with `/tool` is put ahead of the turn. `tool_plan` is gone, and with it the `<tool-plan>` nudge on every turn and the preflight that web-searched a pasted document whole.
- The briefing is written for current models: one short -ing line before a call instead of an eight-word cap and a plan-first opener, no output contract re-sent every turn, memory searched when prior context could change the work, and Claude's notes state goals with their reasons.
- Claude turns ask Claude Code for `high` effort; `RAMABANA_EFFORT` overrides it. Opus 5.5 otherwise runs at medium.
- The Claude 5 series runs with a 1M window: Claude Code is asked for `<id>[1m]`, which it needs to serve more than 200k, and compaction follows that window.
- `sonnet` and `haiku` resolve to `claude-sonnet-5-5` and `claude-haiku-5-5`, and sub-agents default to `claude-sonnet-5-5`.
- Open folders holding more text than `SHELL_SNAPSHOT` are measured once: `run_shell` no longer re-reads them before every command only to give up.
- Usage on the Claude backend accumulates across calls. A turn smaller than the one before no longer records 0.
- dhrona's example rounds are off by default; `--warm` turns them on.
- Requires uraiyadal 0.0.11, whose tag protocol asks for independent calls together.

## 0.2.11

- The Claude Code and Anthropic catalogs list `claude-haiku-5-5`. The `haiku` alias still resolves to `claude-haiku-4-5-20251001` and `sonnet` to `claude-sonnet-5`.
- With `ANTHROPIC_API_KEY` set, the Claude Code picker adds the ids the Anthropic key lists after its curated ones. The `claude` and `anthropic` providers share one cached listing and one request.
- Discovered ids that end in a compact date snapshot, such as `claude-sonnet-4-5-20250929`, are left out of a picker. Curated ids are never filtered.
- Requires rishi 0.1.40, whose Claude backend runs the `claude` on `$PATH` instead of the Agent SDK's bundled copy.

## 0.2.10

- The conversation index no longer rescans the whole log on every read. A title-only row, for a conversation that never logged a turn, used to mark the index stale forever. When the log has only grown, the index reads just the new tail. A full rebuild happens only when the log shrank, a row is from an older index version, or there is no index.
- `_index_turn` catches up first when its line does not follow the indexed end, and a last line without a newline waits for the next read.

## 0.2.9

- Tool results carry pictures to the turn model: a `screenshot` or a `view_file` on a picture arrives as an image when the model takes images and the transport carries them. Otherwise a note names the path. Sub-agents follow their own model.
- Checkpoints, branches and model switches hold a placeholder for pictures, not base64.
- An `after_tool` hook or a queued steer that rewrites a result keeps its pictures (`keep_media`).
- The briefing's screenshot rule follows the turn model. A resumed conversation replays paths, not pictures.
- `MEDIA`, `Attachment`, `media_parts` and `media_note` live in `ramabana.tools`, so a host that only sends files does not import the terminal. `ramabana.cli` re-exports them.
- `teleprint` is capped below 0.1.4, whose `Compositor` has no `release`. Requires shalya 0.1.3 and uraiyadal 0.0.10.

## 0.2.8

- Git writes, commits and rewinds act in the repository a call names: `/commit FOLDER MESSAGE`, `/pr FOLDER TITLE`, and `/rewind` undoes a git change where it happened. A git write with `path=` snapshots the tree rather than recording the folder as a file.
- `restart_kernel` and `page_eval` always ask.
- Sub-agents: `subagent_steps` (1–80, `/subagents steps N`), `subagent_timeout` (seconds, 0 for none, `/subagents timeout S`) and opt-in nesting `subagent_depth` (0–2, `/subagents nest N`). A nested sub-agent gets only synchronous `delegate_search`. One tool-call budget covers the whole tree, and at most four sub-agents run at once. The setters refuse while busy.
- `runs(active=True)` includes background runs; `busy` counts foreground runs only. Finished run children are pruned past 50.
- With the browser opt-in, the briefing says how to look at a screenshot: `delegate_search(questions, images=[path])`.
- Requires `shalya>=0.1.2`.

## 0.2.7

- `resume_session(keep_model=True)` resumes on the turn model in use. The default still adopts the conversation's last model, and the note names the model actually in use.
- `Backend.snapshot_hist` includes a resumed conversation that has not reached the model yet. A `set_model` before the first turn after a resume used to carry an empty history across.
- The log reader splits records at `\n` only. A raw U+2028 inside a record no longer breaks it in two, and one unreadable line costs only itself.
- Catalog adds `claude-sonnet-5-5` and `gpt-6.1-sol`; live provider models list newest first.
- Requires `uraiyadal>=0.0.9`: a tagged tool call keeps its arguments, and one whose arguments were lost is asked for again.

## 0.2.6

- Sub-agents never get the delegation, watch or plan tools, whatever the turn model or budget (a cloud turn used to hand them the root's full list). `ROOT_ONLY` names them.

## 0.2.5

- Enter mid-turn steers the running turn. Shift+enter queues. Shift+tab cycles approvals, with the mode always on screen. Kitty and modifyOtherKeys keys decode.
- The now pane: status lines per agent and sub-agent, the plan, a sub-agent accordion, files touched and background jobs. It opens beside the chat in tmux. `/pane` and `--pane auto|on|off` control it.
- Sub-agent calls show on the activity, stamped with their run; read-only ones are shown, not governed.
- The first run starts ramabana in its own tmux server, one per launch. It asks once to install tmux. `ramabana --doctor` checks the setup. `--tmux off` opts out.
- Edits and `git_diff` finish open on a highlighted diff, capped at `DIFF_OPEN`; changed files show as a table.
- Reply code fences highlight through fastpylight.
- Startup: the prompt draws in about 0.3–0.6 s while the model starts on a thread; the search stack loads lazily.
- `sync_index` runs kosha only when a package or root changed, and logs run or skip to `kosha.log`.
- Routing: Claude Opus takes the turn, gpt-4.1 the small jobs, Sonnet the sub-agents. No local engine sits on a default route. A local turn keeps side jobs local. Without `OPENAI_API_KEY`, gpt-4.1 jobs fall back to Sonnet.
- Extras: `search`, `python`, `serve`, `cli`, `dhrona`, `all`. A missing extra drops its tools and its commands name the extra to install. The core includes what shalya needs.
- Dependency floors raised to current releases.
- Lean prose pass: one-line docstrings, fewer comments. The `03_agent` chats were re-recorded.

## 0.2.4

- Sub-agents see pictures: `delegate_search`/`delegate_async(images=[...])` send pictures (inside the open folders, recognised by bytes, ≤ 8 × 20 MB; pictures × questions ≤ 8) to the sub-agent's model; refused for models that can't take images.
- `generate_image(path=...)` is a write: approvals gate it like other writes (doom-loop guard included), `/rewind` tracks every picture it saves (all of `n`), read-only sub-agents can't pass a `path`. Needs shalya 0.1.1.
- A bare sub-agent model name (`cloud_model="gpt-6-sol"`) resolves to the configured sub-agent model; an unknown name says so.
- Activity keeps string arguments whole up to 2000 characters (dhrona rounds replay full calls); resumed context still shows one short line each.
- Read-only tool copies are recorded like the rest; the recorded mark is per agent and wrapper.

## 0.2.3


## 0.2.2


## 0.2.1


## 0.2.0


## 0.1.42


## 0.1.41


## 0.1.40


## 0.1.39


## 0.1.38

Needs shalya 0.0.11.

- Seams for a frontend that is not the terminal:
  - `Approvals.decide` answers what needs no person, and `Approvals.set_mode` switches and settles.
  - `Agent.expand_command` turns `/name ARGS` into its prompt.
  - `Agent.on_watch` and the `watch` event replace the tmux pane.
  - `Agent.on_background_done` and the `background_done` event fire when a delegation finishes.
  - `Agent.last_verify` keeps the verify text, which `stream` now yields as its last chunk.
- `APPROVE_MODES` lives in `ramabana.agent`; the CLI calls the agent for `/approve`, the tightening key and slash-command expansion.

## 0.1.37
- A `before_tool` hook that rewrites a write tool's arguments no longer raises. The re-approval read a field `Ask` does not have.

## 0.1.36

Needs rishi 0.1.38. Claude transcripts are refiled as tags text. A resumed session keeps using tools.

## 0.1.35

Needs shalya 0.0.10, koshas 0.1.9, vishalakshi 0.1.16, litesearch 0.1.35.

- `delegate_async(writes=True)` is refused while sub-agents are read-only, naming `/subagents on`; the briefing states the ceiling.
- Sub-agents cite the tool call behind a claim and end with `state: completed|blocked|failed`.
- Briefing carries the host's `environment` and rules for pilots before bulk work and verifying a sub-agent's facts.
- `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and `<cfg>/AGENTS.md` reach the briefing; `CLAUDE_NOTES` applies on Claude models.
- Approval prompts show a diff for `replace_text` and the command for `run_shell`; saved rules in `<cfg>/approvals.json`; `--approve edits`; `A` saves an always-allow rule.
- `/commit` and `/pr` draft from the diff and log and go through approvals.
- Background delegations report into the next turn; `run_shell` rule points long runs at `run_shell_bg`; `Agent.close` closes the host.
- A `verify` command from `[tool.ramabana]` runs when files changed without a check; `changed:` line after each turn.
- Checkpoints per turn; `/rewind`, `/branches`, `/branch`.
- Hooks can deny, rewrite args and replace results; `session_start` and `stop` fire.
- `/skill args` and `<cfg>/commands/*.md` run as turns; `--json`, stdin prompts, a warning when one-shot writes would be refused; `--bell`.
- `<cfg>/memory/<root>/MEMORY.md` in the briefing, `#note`, `remember_note`.
- Per-run transcripts under `<cfg>/runs/<session>/`; `/watch`, `/unwatch`, `/tell RUN TEXT`; `--tmux auto|on|off`.
- `own_vault` fixture pins `VIRTUAL_ENV` so usearch loads the patched extension.

## 0.1.34

Needs shalya 0.0.8, uraiyadal 0.0.7.

- A line typed while a turn runs joins the one already queued; both run as one turn. The pending row sits above the prompt; join and send each flash there and clear.
- `ToolCatalog`, `ToolEntry`, `WorkspaceHost`; provider dispatch completed; shalya compatibility boundary narrowed.
- Tools and hosts are shalya's by name; `ramabana.tools` re-exports them for one release.
- Briefing carries the AGENTS.md rules.
- `ModelSpec` subclasses urai's (`backend`->`runtime`, `config`->`opts`, `local` from urai's registry).
- `RUNTIME_NAMES = tuple(urai.RUNTIMES)` replaces the hardcoded `RUNTIMES`.
- `ramabana.tools` no longer claims six names it never had from shalya: `frontmatter`, `_apply_edits`, `_cmds`, `_diff`, `_edits`, `_fuse`.
- Tool kind comes from shalya `group_of`; `_KIND` holds only differences. Git group gains a kind; `DELEGATE_TOOLS` names all six delegates, so every delegation kind nests.
- Approval prompts use shalya `summarise` (`Edit a.py`), matching the activity log.
- `Usage` reports reasoning and cache-write tokens; both read zero before.
- Pump thread joined before its pipe is closed.
- `atomic_save` for probe, alias and session writes.

## 0.1.33

Built against the local shalya checkout so both can be tested together before release.

### New

- `probed`: single memo for machine-probe answers. It serves the last answer, refreshes stale ones on a background thread and persists to disk. Replaces `_oai_cache` and `_copilot_cat`; `_openai_models` and `copilot_catalog` now go through `probed(..., disk=False)`. `probe_path` and `forget_probes` included.
- `runtime_detail`: explains why a harness runtime is unreachable. `runtime_remedy` already said what to do; now `runtime_detail` says why. `HARNESS` lists both harnesses and their requirements.
- Persistent model aliases: `save_model`, `load_models`, `delete_model`, `saved_models`, `alias_path`, `MODEL_ALIASES`. `register_model` remains the in-process form. Defaults to `~/.config/ramabana/models.json`.
- `Agent.memory_context(surface, max_chars)`: seam for applications with a vault. Previously the completer looked for `self.a.ws.agent_memory_context(...)`, which nothing in Ramabana set, so pinned notes never reached completions.
- `mk_host` / `mk_agent` forward host kwargs (e.g. `index=False`). Previously only `pii` was reachable.

### Fixed

- `sub_briefing` matched sub-agent read-only sentences by text; 0.1.32 reworded them, breaking the match. Now assembled from `SUB_SP_HEAD` + `SUB_READ_SP` / `SUB_WRITE_SP`. No text matching.
- `cart_add` / `cart_remove` were in `WRITE_TOOLS` but lacked `@writes`, so `read_only` missed them. Read-only agents could modify carts.
- Image group captured the model at tool-build time; `set_model` only rebuilt when the budget changed. Switching to a non-drawing model left it drawing as the old one.
- `tests/test_vault.py` opened an indexed vault via `mk_host`, triggering concurrent downloads of a native SQLite extension from unjoined daemon threads. This segfaulted the interpreter.
- Three string assertions broken by 0.1.32 rewording (reviewer briefing, compaction reminder, summary-update prompt). Now assert the full value, not a substring.
- `--agent-proxy` flag test asserted the underscored spelling that fastcore no longer generates.
## 0.1.32

The toolset moved to [shalya](https://github.com/vedicreader/shalya), and git plumbing moved to [gheasy](https://github.com/vedicreader/gheasy). `ramabana.tools` and `ramabana.git` re-export the moved names. Existing imports still work.

- `/python` now assigns a kernel backend instead of replacing the host, preserving all fifteen tools in `ramabana --vault --spec`.
- `Host.capabilities` is now `Host.provides`. Hosts declare capability groups by inheritance; incomplete declarations fail to build. `_declared`, `_probe`, `_supports`, `_has`, and `_takes_reading` were removed.
- `public_api` is available only to hosts with a code index.
- `mk_host` uses the declared `VaultSpecHost` instead of creating a class per session.
- `AgentError` aliases `shalya.core.HostError`. Existing `except AgentError` handlers still work.
- `ramabana.git` re-exports `_run`, `_conflict_blocks`, and all three git tool sets from `shalya.core`.
- The local `[tool.uv.sources]` overrides for `shalya` and `uraiyadal` were removed; both now install from PyPI.
- `--pii off|redact|refuse` and `--pii-ner` now reach terminal, MCP, ACP, and vault hosts. `off` remains the default. Using `--pii` without `--vault` exits with status 2.
- `read_only` now comes from shalya. `NO_EFFECTS`, `NO_KEEP`, and `_pinned` were removed. `effects=False` withholds shalya's acting tools; Ramabana supplies `block=NO_SUB`.
- `read_url` accepts `remember=True` or `remember=False`. Only `read_only(..., writes=False)` substitutes the restricted form, which uses `remember=False` and omits the argument from the model's tool schema. `read_only(..., writes=True)` retains the ordinary tool.
- Tool activity summaries now live beside tool docstrings and use shalya's `summarise`. Missing summaries fail tests instead of silently omitting activity.

## 0.1.31
one shot model should error loudly if it can't take the context

## 0.1.30
read tools should not allow remember in vault. to be used by completions and inline model in leela

## 0.1.29
fixes delegate search errors

## 0.1.28
drop stale subagents


## 0.1.26
threads manage their own vault connections

## 0.1.25
git lfs binary diffs

## 0.1.24
acp, agent monitoring, claude fixes

## 0.1.23
cli streaming + local model fixes

## 0.1.22
cli, themes, runtime fixes

## 0.1.21
removed claude cli and converged on one claude sdk model

## 0.1.20
cli fixes to default graph indexing to false and splitting prose

## 0.1.19
plan displays once and is repainted and in theme. auto tool budget flows through

## 0.1.18
cli fixes to remove claude models tool calls as tags. remove multiple tool results in ramabana cli.

## 0.1.17
slopometer v2

## 0.1.16
slopometer fixes

## 0.1.15

### Packaging

- Source distributions now contain the package, README and project metadata only. Notebooks and tests are no longer included.

## 0.1.14

### Fixed

- The `all` extra now installs `rishi[all]`, including every Rishi backend. The `copilot` extra remains available separately.

## 0.1.13

### Changed

- Refreshed the resolved development dependencies.

## 0.1.12

### Added

- Added GitHub Copilot as a runtime. Ramabana detects an existing Copilot sign-in, lists the models available to the account and uses each model's reported context window.

## 0.1.11

### Added

- Published `theory`, `write_prose` and `write_docs` as pyskills, and refreshed `coding_patterns`.
- Added optional write access for sub-agents. Sub-agent writes use the parent session's approval policy.

### Fixed

- Resumed sessions now retain tool calls and tool results instead of restoring only the visible transcript.

## 0.1.10

### Changed

- `tool_channel` now asks the live chat whether tools are native or tag-based. Tool budgets and briefings no longer treat native Cursor and Claude tools as tag tools.
- Cursor and Claude Code runtime configuration now follows the capabilities reported by their active transports.

### Fixed

- Git rebase previews are treated as reads and no longer block unrelated requests behind the write queue.

## 0.1.9

- Version-only release.

## 0.1.8

- Version-only release.

## 0.1.7

### Added

- Added Git status, divergence, rebase preview, remote synchronization and branch checkout tools. Git operations use rehearsed safepoints before changing a branch.

### Changed

- Tool-call limits can now be selected automatically from the active model and task.

## 0.1.6

### Added

- Added multimodal input for images and audio, generated-image tools, runtime capability reporting and image blocks in the terminal transcript.
- Added OpenAPI specifications as dynamically loaded tool groups.

### Fixed

- Generated images now reach the transcript during the turn and render as complete, non-folding blocks.

## 0.1.4

### Changed

- Tightened the agent system prompts and rendered tool calls on one line.

## 0.1.3

### Changed

- Kosha index synchronization now runs in parallel.

## 0.1.2

Adds a Python prompt, `ask_memory`, a read-outside mode, attachments and clipboard paste. Fixes bugs in the host, the code index and the terminal.

### New

- `ramabana --python`: a Python prompt whose namespace is yours. The agent reads the namespace through Dhrishti's sandboxed overlay and cannot rebind anything it did not create. It is a mode of the one terminal, not a second program. `/python` starts the kernel and takes the line, and `/agent` hands it back. `--attach` locks into a kernel that is already serving, which is how it runs inside leela.

### Added

- `ask_memory`, and `Host.ask` behind it, ask remembered research a question and return a short cited answer instead of the sections. `delegate_search` makes the same trade. `ask_memory` appears only for a host that implements `Host.ask`.
- Private material is answered on this machine. `vishalakshi.pii` decides arithmetically, without asking a model to read the material first, whether the sections that a question retrieved hold personal information. When they do, a local model computes the answer under a briefing that forbids it to repeat any personal detail to the caller. The answer says what the model is holding and what instruction would let it answer usefully. The caller sends that back as `instruction`, and the model gets another turn on the same sections. The runtime is checked on the chat object before any character is sent. A lent hosted chat is refused. `pii='off'` is not reachable from the far end of a tool call.
- `Agent.lend_model`'s factory honours the model it is asked for (`Agent._spec_for`). A request for the local model gets the local model.
- `Host.capabilities`: a host declares which tool groups it supports, and `tools_for` asks before it probes. The probe is the first thing to touch a host. A capability whose answer sits behind a model load made the probe wait. `VaultHost` opens its vault in the background so the tool list does not wait, and `memory_tree('')` then blocked on the lock that thread holds. On the first `Agent.tools` access this took 3.0 s against a stub, and it waited for a whole embedding model against a real vault.
- `Agent.poll_watches` and `Agent(poll_every=)` are the tick that the watch feature was built around and nothing ever called. A turn is the tick, run in a daemon thread. Whatever fires files itself into memory. `VaultHost.connect` does the same for the entity graph, which `research` used to rebuild inline on the one path where the user is waiting.
- `Host.grep`: a host with a fast exact matcher answers it. `LocalHost` does through ripgrep, over exactly the files `walk` yields. The tool used to read every file through `host.read`, and therefore `check`, and therefore a `resolve` per file.
- `Agent.snapshot_tree` and `SHELL_SNAPSHOT`: `changes()` keyed on a tool argument named `path`, and `run_shell` has none. A command that rewrote twenty files reported `{}`.
- `LocalHost(rerank=, rerank_model=)` wires Kosha's cross-encoder through to both context calls. It falls back once and stops asking if flashrank cannot fetch its model.
- `LocalHost.indexed` gives per-folder index readiness. A small repo goes semantic while a large one is still syncing. `index_ready` now means all of them.
- An `oneshot` routing job. `Routing.spec` falls back when a job's model is not installed here. `inline`, `completion`, `classify` and `summary` take it unless singled out.
- `Agent.lend_model` and `VaultHost(mk_chat=)`. vishalakshi builds a chat per `ask`. On a local model that is a second copy of an engine already in memory, and it answers on a different model from the one being talked to.
- `core.claude_tags` and `$RAMABANA_CLAUDE_TAG_TOOLS`. Claude Code declares tools as an in-process MCP server, and an enterprise-managed configuration forbids every dynamic MCP server. The tools were stripped and the model ran blind. With the new option the tools travel in the system prompt through Rishi's `tool_mode='tags'`.
- `LocalHost(read_outside=True)`: a read may name any path on the machine, and a write may not. Confining writes stops an agent from damaging something nobody opened. Confining reads stops it from answering a question whose answer is in a sibling checkout or a library outside the venv. Enumeration is unchanged either way: `walk`, and therefore `grep` and `list_files`, never leave the open folders. A read outside is always a path the model already knew, never one it found by looking. `DENY` is the short list of credential paths refused regardless. `--read_outside` works on both `ramabana` and `ramabana-mcp`.
- `Host.check` takes `reading=`, and the read-only tools resolve through the new `tools.readable`, which checks the signature first. The flag is a host capability, and a host written before it sees the call it always saw.
- `cli.Option`, `options_for` and a reworked `ChoiceMenu`: the two-choice refactor prompt became a component. A prompt whose reading matters gets a titled row of options above the input line, each with the instruction it appends. Arrows, digits or the option's own letter pick one. Cancelling hands the typed line back to the composer instead of dropping it.
- `cli.mk_host`, and `--vault` on both frontends. Durable memory through `VaultHost` was reachable only by writing Python, and neither frontend could use vishalakshi.
- Attachments in `ramabana.cli`: `MEDIA`, `Attachment`, `media_path`, `media_paths`, `attach_refs`, `media_parts`, `media_note`, and `Ui.attach`, `detach` and `attach_row`. A prompt carries up to `MAX_ATTACH` files, images and audio, named the way a terminal hands files over: dropped on the window, pasted as a path, or written `@path` in the sentence. Every shape that a terminal delivers a drop in resolves to the same attachment: quoted, bracketed, a `file://` URI, spaces backslash-escaped, several at once. Before, only a bare unquoted path did, and dropping a picture on the prompt usually typed its path. Pictures go out as content parts. Every attachment is also named by absolute path, so a runtime with no ear for audio can still reach a `.wav` through the file tools. Chips above the prompt say what the next message carries. Only the turn that named the attachments carries them.
- `Ui.attach_clipboard` and `clipboard_png`, on `ctrl+v` and `/paste`. Bracketed paste carries text only, and a copied image never arrived as input. The picture is asked of the platform (`pngpaste`, `wl-paste`, `xclip`). A missing helper gives a plain sentence instead of a silent no-op.
- `Ui.copy_last`, on `/copy`, copies the newest reply to the system clipboard over OSC 52 without leaving the prompt for the transcript view.
- `Ui.note`, `Ui.touch`, and `Ui.enter_transcript`/`leave_transcript`.

### Fixed

- `Agent.changes()` was blind to `run_shell`. It keyed on a tool argument called `path`, and a command names no files. `black .`, a codemod or a `git checkout` can rewrite twenty files and mention none of them, and the answer came back `{}`. The README points at `changes()` as the thing that knows what moved.
- `_named` dropped the positional half of a mixed call. The code was `args = kw if kw else _named(f, a)`. `edit_file('a.py', commands=...)` was recorded with no path. That gave an unreadable activity line and a file that was never snapshotted, because the path `changes()` looks for is that one.
- `LocalHost.search` tried its legs in order instead of fusing them. A rename whose query happened to embed well lost its own call sites. Both legs run now, and `fossick.rrf` merges them.
- `read_url` promised "(or GitHub file, arxiv paper)" and plain-fetched both. It routes to fossick's own readers now. It escalates through `fetch(auto=True)`: plain, heavy, stealthy, logged-in Chrome. Before, it jumped from plain to a stealth browser.
- Kosha was told to sync serially (`in_parallel=False`, overriding its own default). `index_ready` took minutes, and every search until then was literal.
- `resolve` checked `runtime_available` for a `vendor/model` name and not for a short one. `resolve('qwen-4b')` succeeded on a machine with no MLX. The job built a backend, `start()` failed, and `Agent.oneshot` returned `''`. The cheap jobs did not error. They stopped happening.
- `LocalHost(roots=())` raised `IndexError` out of `check`. It is a legal host. It refuses paths with an `AgentError` that says why.
- `ramabana.core` wrote into `sys.modules` at import time and rearranged `toolslm` for every other consumer in the interpreter. The shim is installed at the two points that need it.
- `scale_numeric` is gone. It was a pandas min-max scaler in the permanent tool list of a general coding harness.
- `RishiBackend` reached into five Rishi privates (`_oneshot`, `_sys_pre`, `toolspecs`, `ns`, `_recreate_conv`). Rishi grew `Chat.oneshot` and `Chat.reconfigure`. `think=False` now applies on every runtime, not only MLX.
- `LlamaBackend` and `FastllmBackend` warn as deprecated aliases for `RishiBackend`.
- `pyproject` refused to install below 3.12 while its classifiers claimed only "Python 3".
- An attached image shredded the rest of the message. `compose` returns a list of content parts when there is an image, and `_prepare` then did `list += str`, which extends a list one character at a time. Every multimodal turn reached the model as the image followed by several hundred single-character parts, with the tool plan and every preflight result scattered among them.
- `Approvals` refusals that nobody could be asked about (`mode='off'`, or no listener registered) never reached `on_answer`. The reason existed only in the model's context, and the user saw an unexplained tool failure.
- `Agent.checkpoints` grew for the life of a session and held a deep copy of a whole conversation per turn. It is capped at `MAX_CHECKPOINTS`.
- `/skill NAME` was `return self.oneshot and clip(...)`, a bound method used as a truth value, left over from an earlier version.
- The briefing and `tool_plan` still named leela, and told a model working on any other project about an editor that is not there.
- `captured` read `$LEELA_NO_NATIVE_CAPTURE` directly. The switch was unreachable under the prefix that `use_env_prefix` sets. It goes through `env` now, and the old name still works as the fallback.
- The activity feed had no summary or icon for `run_shell`, `grep`, `ls`, `replace_text`, `create_skill` or any of the memory, watch and cart tools. The shell call, which a person most wants to read back, rendered as `run_shell(command='…')` under a wrench.
- `Ui.submit` tested for a refactor question before it recognised a slash command. `/model refactor-thing` opened a menu instead of running.
- `_supports` was written as a general capability probe and hard-coded `run_cmd` in its body.
- With an agent, the MCP server now mounts the agent's own recorded tools, as its documentation already claimed. A client's call appears in the same activity feed and the same `changes()` as a call the model made for itself.
- The code index never built the call graph it searches through. `sync_index` passed `sync_graph=force`, kosha's deprecated name for `graph`, and `force` is `False`. Every ordinary sync ran with `graph=False`, while `_semantic` went on asking `Kosha.context` for graph expansion over a graph that was not there.
- `LocalHost.web_search` sliced fossick's results to `n` instead of asking for `n`. fossick's own default is 10. A request for twenty results returned ten.
- `LocalHost.research` stringified the whole `{query, sources, digest, dropped}` record that fossick returns. `digest` is the cited markdown, and `sources` is the same markdown again per page. The model was handed both copies wrapped in Python dict syntax.
- Four tests asserted against `fastllm.chat` privates (`_alite_call_func`, `AsyncChat.tcdict`) for a shim this package no longer installs. They had been failing since that library changed its internals. They are replaced with tests of the approval behaviour they were protecting.
- Copying a reply returned the screen, not the reply. No block passed Teleprint a `source`, and `set_body` clears it unless given one. `y` and search fell back to scraping the rendering: prose re-wrapped to the terminal's width, and code indented by the gutter and stripped of the fences that made it paste-able. Every block now states its own text, and a plain string or `Text` states it for free.
- The transcript view froze during a turn. It is entered pinned to the tail (`less +F`), but nothing ever called `TranscriptView.notify`, and `set_tail` goes model-only while the alt screen owns the tty. A streaming reply, arriving tool calls and the status bar all stopped until the next keystroke. `Ui.touch` and `Ui.paint` now drive it, rate limited by `NOTIFY_EVERY` because a rebuild re-renders every block in the model.
- Mouse reporting was on everywhere. That took drag-select away from the terminal, the ordinary way anyone copies out of a scrollback, and in the main screen it was used for nothing but accidental fold toggles. It is now switched on only while the transcript view is up. This is Teleprint's own division: the main screen belongs to the terminal.
- `/help` described keys the app does not have. `↑`/`↓` enter the transcript and do not walk prompt history, which is `ctrl+p`/`ctrl+n`. `ctrl+y` yanks.
- The attachment hint overwrote the roots hint permanently and outlived the turn it described. The status line went on claiming an image was attached after it was sent.
- Cancelling the refactor menu with `esc` discarded the prompt that opened it. It now returns to the composer.

## 0.1.1
Adds `VaultHost` memory, standing watches and a shopping cart extension.

### Added

- `ramabana.vault.VaultHost` is `LocalHost` with a [vishalakshi](https://github.com/vedicreader/vishalakshi) vault behind it. One SQLite file provides three things. The five `memory_*` tools have something to answer from, and `tools_for` stops dropping them. `search_code` fuses the vault's prose with kosha's identifiers and ripgrep's literals by RRF, not by distance, because the legs share no vector space. `read_url` and `research` file what they fetch. What the model reads and what the next session can recall are the same text. A vault that will not open degrades to exactly what `LocalHost` did.
- Standing interests on `Host`: `remember`, `watch`, `watches`, `unwatch` and `poll`, with `watch_tools` behind the same capability probe that every other group uses. A reminder is a watch whose action files its own text back into memory when it comes due. "What am I supposed to be doing" and "what do I know" are one query, and neither needs a notification channel that the harness does not own. One failing watch is recorded on its row and not raised.
- `ramabana.shop`: `Cart`, `FossickCart` (a real logged-in Chrome via `fossick.shop`), `FakeCart` and `cart_tools`. It registers as an extension and is not part of `Host`. `cart_add` reports whether the cart moved, not whether the click worked.
- `08_shop.ipynb` runs the whole flow end to end: a reminder set once, polled a week later and acted on across two stores. Only the model's decisions and the trolley are mocked.

### Changed

- `WRITE_TOOLS` gains `cancel_watch`, `cart_add` and `cart_remove`. An `Approvals` policy now draws its line around more than the filesystem. Deleting someone's standing reminder and spending their money both go in front of a person.

## 0.1.0

The notebooks and modules now match one to one. Adds a terminal app and an MCP server.

### Breaking

- Modules consolidated to match the documentation pages. Each notebook is now exactly one module, which is the only layout from which `nbdev-export` produces the same output on every run. Old imports map as follows. The names exported from `ramabana` itself are unchanged.

  | was | now |
  |---|---|
  | `ramabana.models` | `ramabana.core` |
  | `ramabana.native`, `.compact`, `.backend` | `ramabana.runtime` |
  | `ramabana.host`, `.skills`, `.extensions`, `.subagent` | `ramabana.tools` |
  | `ramabana.activity`, `.hitl`, `.fastllm_hitl`, `.chat` | `ramabana.agent` |

### Added

- `ramabana.tools.LocalHost` is a `Host` over real folders and a live namespace in-process. It has sandboxed path resolution (`..` and symlinks are resolved before the check), automatic `Kosha.sync` in a daemon thread, repo-first semantic and keyword search across the open repository and installed packages, `ast`-based symbols and peers, notebook cells, and a persistent exec namespace. It is the reference implementation, and both frontends run on it.
- `ramabana.cli` is a terminal app on [teleprint](https://github.com/answerdotai/teleprint). It has a transcript of foldable blocks, a live status bar, streaming replies, tool calls as blocks, and the approval gate on the input line. Run `ramabana` or `ramabana -p 'one question'`.
- `ramabana.mcp` serves the same tools over MCP, read-only by default, plus an `ask` tool that runs a whole Ramabana turn when a model is configured. The command is `ramabana-mcp`.
- `ramabana.testing.FullHost` is a host with every capability present over a throwaway folder, including a research-memory index and a web that returns the pages it was given. The whole tool surface can be tested against it. Its release check loads a real MLX model through rishi and verifies all 28 tool functions and all 28 compiled tool schemas.
- `ramabana.runtime.answer_only` strips a reasoning model's thinking from a one-shot reply.
- `ramabana.runtime.prefills_think` and `ThinkFilter` are the streaming half of the same problem. `prefills_think` asks a model's own chat template whether it opens a `<think>` block and leaves the model to close it. `ThinkFilter` drops that block out of a streamed turn and re-arms at every tool call, because such a template opens a fresh thought per step.
- `ramabana.tools.ld_json` returns a page's `schema.org` JSON-LD blocks, which is where a product page states its price. `LocalHost.read_url` now prepends them to the prose.
- `mini-coder-4b` (`mlx-community/mini-coder-4b-OptiQ-4bit`) joins the MLX table and becomes the default for inline `completion`. A 4B model trained on code finishes a line better and faster than a general 9B. Every other cheap job stays on the default local model.

### Fixed

- Reasoning models broke every cheap job. `classify`, `summarise`, `Completer` and compaction all read a one-shot reply as data, and all four returned the model's `<think>` block instead of its answer. `Backend.oneshot` now strips the block, including the unpaired closing tag that arrives when the chat template opens the block in the prompt.
- Inline completion could insert prose into your file. A small model asked for bare code explains itself first and then opens a fence that the token cap cuts off before it closes. `_clean` took the whole reply. It now keeps only what follows an unterminated fence, and suggests nothing when there is nothing but prose.
- `nbdev-export` works again (it raised `TypeError` in `nbdev/maker.py`) and is idempotent. The custom `tools/export.py` that had replaced it is gone. `nbdev-clean` is a no-op, and `nbdev-test` executes every notebook. Generated modules carry the `AUTOGENERATED` header, real `__all__` lists, module docstrings and doclinks again.
- Relative imports in exported cells (`from .core import ...`), which `nbdev-export` refuses.
- A streamed turn leaked the model's thinking into the reply. Rishi's splitter waits for an opening `<think>` to know it is inside a thought. A model whose chat template writes that tag into the generation prompt, such as Ornith-1.0-9B, never emits one. Its deliberation arrived as ordinary reply text with a stray `</think>` in the middle. `_stream` now filters the structured chunk stream and renders what is left with Rishi's own formatter. This was the release's one Known limitation, and it is gone.
- A cheap job could not answer at all inside its own budget. `classify` allows thirty-two output tokens, and a reasoning model spends all thirty-two thinking. No answer was left for `answer_only` to uncover. The one-shot conversation is now built with `think=False`, which closes the template's thinking block in the prompt. The model answers immediately.
- The first cheap job capped every one after it. `_oneshot_chat` is reused across jobs and was constructed with the first caller's `max_output_tokens`. A 32-token `classify` left a 32-token ceiling behind, and the next `summarise` came back cut off mid-sentence. Each call now passes its own cap explicitly.
- `read_url` could not read a page that renders in the browser. A site that turns away scrapers answers `200 OK` with an empty shell and no error, so escalating on the status code never fires. `LocalHost.read_url` judges the extracted text instead. It escalates to a real browser only when there is too little text to be a page.
- `local_ctx('ornith-9b')` silently returned the fallback window. The table keyed it `ornith_9b`, with an underscore, while the model alias has a hyphen.

### Docs

- Every notebook is a literate page. Sections have exported summaries that assemble into the module docstring, and executable examples double as the tests. This includes the terminal UI, asserted against a headless terminal emulator, and the MCP server, asserted through real `list_tools` and `call_tool` round trips.
- `nbs/index.ipynb` ends with one real problem solved end to end: a routed agent over this repository and the live web. It finds a constant with the code index, finds a supermarket price through a browser, and closes with arithmetic that needs both. The turn runs on a hosted model, and every cheap job runs on a local MLX one. Those cells are `eval: false` with their real outputs stored, so neither CI nor the docs build needs a GPU or a network.
