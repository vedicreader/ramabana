# Decisions

This page lists the decisions that a maintainer must know. Each entry gives the decision, the reason, the version or date, and the place in the code.
The rules of daily work (kosha first, notebooks are the source, the coding patterns) are in [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md), and the patterns are in `nbs/09_coding_patterns.ipynb`. This page does not repeat them.
The release notes are in [CHANGELOG.md](../CHANGELOG.md). The old plans (Claude Code parity, Leela integration, the embedding host, peer talk) are in the git history under `docs/`.

## Models and routing

- **rishi does every model call; ramabana is the agent layer.** Each backend is a `RishiBackend`. Apps (abhyasa, Leela) go through ramabana, not bare rishi, so they get routing, fallbacks and guards. A direct `make_backend(resolve(name))` skips all three.
  (Owner, Oct 2026) `make_backend` in `nbs/01_runtime.ipynb`, `resolve` in `nbs/00_core.ipynb`.
- **Each job has its own model.** Jobs: `turn`, `oneshot`, `inline`, `completion`, `classify`, `summary`, `subagent`. Defaults are in `DEFAULT_POLICY`. Override with `$RAMABANA_MODEL_<JOB>`, `[jobs]` in config.toml, or `routing.set(name, job)`. `Routing` in `nbs/00_core.ipynb`.
- **A model that cannot run falls back.** `Routing.spec(job)` tries the turn model, the other jobs' models, then `gemma-e4b` on the device. A cloud model that fails or answers empty is set aside for `DOWN_TTL` (300 s). `Agent.oneshot` tries the next route on failure. `Backend.oneshot` never waits: a busy backend gives `if_busy`.
- **Spending caps.** `Agent(max_cost=, max_tokens=)` stops a turn with `state='budget'`. A runtime with no cost is priced with `est_rate` (10 USD per million tokens). A Claude Code turn gets the cap as its own `max_budget_usd`, because Claude Code reports cost only at the end. (0.2.90, 0.2.96) `nbs/03_agent.ipynb`.
- **Compaction has two absolute lines.** Past `SOFT_LINE` (150,000 tokens) the next clean turn boundary hands off to a fresh context. Past `HARD_LINE` (250,000) the conversation compacts.
  Why: a model works best well below its window, and on a 1M window "when it no longer fits" was almost never. (0.2.91) `nbs/01_runtime.ipynb`.

## Embedding in a host

- **A host drives an `Agent` from Python.** The embedding-host plan (12 Oct 2026, items 1 to 14) is in: many pending approvals answered by id, `no_listener` and `on_timeout` policies, `Approvals(policy=fn)` before rules and modes, an `awaiting` act for a pending ask, read-only roots (`read_roots`), `ask(schema=)` with `TurnResult`, `SessionBusy` on a held session, budgets, `queue`, `events_to`, `extra_sp`, `global_skills=False`. `nbs/03_agent.ipynb`.
- **The loop guard (`DOOM_LOOP`) sits above the approval policy.** A third identical call still asks. `nbs/03_agent.ipynb`.
- **`mk_agent(python=)` is `'host'` or `'off'`.** Python mode, the ACP server and the `shop` module were removed. (0.2.91)
- **Secrets never reach a model or a log.** A tool names `secret_args`; they show as `[SECRET]` in rows, approvals, events and history. Every read passes the key guard. `ramabana.guard.outgoing` masks secrets for each model, local models too. (0.2.82, 0.2.87, 0.2.96) `nbs/27_guard.ipynb`.
- **Instruction files.** The briefing reads `CONTEXT_FILES`: `AGENTS.md` and `CLAUDE.md` variants, `.leela/AGENTS.md` and `CLAUDE.local.md`. `CLAUDE_NOTES` is added for a `claude/*` turn model. (Parity plan, 22 Sep 2026) `nbs/03_agent.ipynb`.
- **Approvals persist as rules** in `<cfg>/approvals.json`, with modes `off`, `ask`, `edits` and `auto`. `decide()` is separate from the wait, so Leela reuses the decision. (Parity plan, Leela plan, Sep 2026)
- **All tools are offered by default.** `drop_tools` in config.toml or `Agent(drop_tools=)` leaves tools out. (0.2.94)

## Background work

- **A finished background job comes to the agent; the agent does not poll.** A sub-agent answer or a shell exit arrives with the next tool result, or wakes an idle session. In `auto` and `edits` the agent goes on; in `ask` and `off` it reports and changes no file. A `shell_stop` kill or a typed `!COMMAND` does not wake it. (0.2.91, 0.2.93, 0.2.98)
- **Git writes go through git tools with an undo token.** `run_shell` refuses `git merge` and `git rebase` and names `git_sync`. The agent is never offered a reset. (0.2.95) shalya's git tools.

## Peer talk

- **Sessions on one Mac talk through `ramabana peers`, `tell`, `inbox`, `together` and `report`.** Ramabana sessions listen on `runs/<session>/control.sock`. Claude Code and Codex register `cfg/peers/<kind>-<id>.json` through hooks. Every message is in `cfg/peers/log.jsonl`. `$RAMABANA_PEERS` moves the folder.
  Why: the owner carried every update between sessions by hand. (28 Oct 2026, 0.2.85) `nbs/23_peers.ipynb` to `nbs/26_peer_report.ipynb`, `nbs/20_control.ipynb`.
- **The receiver decides.** An ask asks the receiver's user first, also in `auto`, unless work together mode is on with that sender. Work together mode does not change tool permissions. It ends at `--until`, after 12 h (`TOGETHER_HOURS`), or with `off`; a typed line does not end it in a ramabana session. (0.2.85, 0.2.97)
- **Limits stop loops.** `HOP_MAX` (6) messages in a thread. `PEER_BUDGET`: 80 messages and 20 peer turns in 12 h. `RAMABANA_PEER_HOPS`, `RAMABANA_PEER_MESSAGES` and `RAMABANA_PEER_ASKS` change them. (0.2.85, 0.2.96) `nbs/23_peers.ipynb`.
- **A turn that a peer started cannot call `work_together`.** A peer must not turn on the mode that frees it. (0.2.97)
- **A session does not edit a folder that another live session holds.** A Claude `PreToolUse` hook and a ramabana approval policy refuse it. The session sends the owner a message. (0.2.85) `folder_denial` in `nbs/23_peers.ipynb`.
- **"Done" needs proof.** A reply carries `changes` and `proof`; the report marks a "done" with no proof as not proven. The `peer-work` skill gives the protocol. `nbs/24_peer_work.ipynb`.
- **`ramabana setup peers` shows a diff and writes only on yes.** The hooks run this ramabana's own Python by absolute path, so run it from the upgraded uv tool. Plain `ramabana setup` does not install them. (0.2.85, 0.2.86) `nbs/25_peer_hooks.ipynb`.

## Terminal and tmux

- **ramabana runs in its own tmux server**, never the user's default one. It removes dead `ramabana-` sockets before it starts (`prune_sockets`). (0.2.99) `nbs/19_setup.ipynb`.
- **The tmux client keeps the ramabana command line in its arguments.** Sanketa finds ramabana there. 0.2.99 moved it to `$RAMABANA_ARGV`, and Sanketa lost the layer, so 0.2.102 put it back. `Setup.wrap`, `HOLD` (`set -m`, own process group). (0.2.101, 0.2.102)
- **One key table drives the key card, `/help`, the hint row, the tips and Sanketa's keymap** (`~/.config/sanketa/keymaps/ramabana.json`). (0.2.83) `nbs/05_cli.ipynb`.

## Tests and build

- **Tests never touch the real `~/.config/ramabana`, the user's tmux server, a browser or window focus.** Use a temporary `cfg` and a `ScriptedBackend`. Mark a test that spawns the agent or drives a real runtime `slow`. `nbs/04_testing.ipynb`, `pyproject.toml`.
- **The build is hatchling.** Extras: `search`, `serve`, `dhrona`, `abhyasa`, `cli`, `all`, `dev`. CI and the docs build install `.[dev]`. The local nbdev must match CI. `pyproject.toml`.
