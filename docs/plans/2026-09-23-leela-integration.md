# Leela integration plan for ramabana 0.1.35+ and shalya 0.0.10

Leela pins `ramabana[cli]==0.1.34` and `shalya>=0.0.9`. Bumping alone is safe: the new shalya host methods are non-abstract, `Agent.close` hits a no-op, hooks and transcripts start working under `~/.config/leela`, and `session_start` and `stop` fire through leela's `Assistant`. What does not work without code: approval rules and the `edits` mode, because leela's `Interventions.request` re-implements the gate; `/agent/runs/{id}/steer`, which looks for a `run.steer` that never existed; and the verify footer, which `Agent.stream` never yields.

## Feature by feature

**Approvals.** Keep leela's structured `tool_preview`; it renders diff rows rather than text. Fix `turns.py` reading `args['edits']` where shalya's `replace_text` takes `spec`, so its diff is currently empty. Pass `rules_path=agent_cfg()/'approvals.json'` when building `Interventions`, and have its `request` call the base decision before leela's control-mode checkpoint. UI: an "Always allow" button on the approval card, an "edits run, the rest ask" option in the composer control, and an "Approval rules" list in settings with delete.

**Sub-agents and monitors.** `/agent/runs` already returns each run's `log`. Add a bottom-dock transcript tab that tails `<cfg>/runs/<session>/<run>.log` over SSE, opened from a sub-agent row, the runstrip, or `/watch`. Override `Assistant.watch` to emit a `watch` event instead of calling `host.open_pane`. Point the steer route at `Agent.tell` and rename the button to "Message". Wrap `ai.background.on_done` to paint a "background result" card when a delegation finishes while idle. Monitors get a runstrip row that opens the same panel on `monitors.log`.

**Terminal.** `terminal_text` already reads leela's pty scrollback, so nothing changes there. Implement `run_cmd_bg`, `cmd_output`, `cmd_stop` on `WorkspaceHost` with shalya's Popen-and-log path and leela's `venv_env`, not through `Terminals.open`, since a `Pty` only fills scrollback while a tab streams it. Show the log in the transcript panel labelled as a terminal tab, with a stop button. Implement `environment()` from `ws.envs()` and `runtime_label` plus shalya's lines minus tmux. Leave `open_pane` unimplemented.

**Checkpoints.** Keep leela's `turn_transactions`, conflict check and journal. Make `turn_capabilities` and `rollback_turn` fall back to `checkpoint_dir/<turn>.json` so "Restore files" survives a restart. Do not call `Agent.rewind` for files; it would raise a second approval.

**Verify footer.** Once ramabana exposes the verify result, add `changed` and `verify` to the `_done` payload and render them as a small row in the revision bar, styled as failed on a non-zero exit. A settings row writes `ws.verify`, forwarded as `Assistant(verify=...)`.

**Hooks and instructions.** Settings gets a "Hooks" table writing `hooks.json` and calling `/reload`, with `registry.notes` under it, and a "Project instructions" section listing the `CLAUDE.md` and `AGENTS.md` files the briefing picked up, with open links.

**Memory.** Leela declares `MemoryHost`, so the file memory and `remember_note` tool stay inert. Wire `#note TEXT` in the composer to the vault's `remember_agent_note` and include it in the agent-memory selection.

**Also.** `/commit` and `/pr` work unchanged; surface the drafted message into leela's own commit dialog by calling `oneshot(diff, COMMIT_SP)` rather than committing blind. Render a sub-agent's trailing `state:` line as a badge on the delegation card. `/agent/ask` gains `changes` and `changed` to match `ask_once`. Command files under `<cfg>/commands` need the expansion seam below. `Threads.shutdown` should call `ai.close()`.

## Ranking and sizes

1. Approval rules, `edits` mode, always-allow, rules list. M
2. Transcript panel, Message, background result card. M
3. `changed:` and verify footer. S, after the ramabana seam
4. `run_cmd_bg` and `environment()` on `WorkspaceHost`. S
5. Restore-files from checkpoint files. S
6. Hooks and project-instructions settings. S to M
7. `#note` to vault, state badge, commit and PR drafts in the git dialog. S each
8. `/agent/ask` parity, command files. S

## First sprint

1. **Rules and edits mode.** Accept: a saved allow rule for `replace_text` on a path runs without a card and the activity row says so; "Always allow" on a `run_shell` card writes the command and the same command does not ask next turn; `edits` lets `edit_file` through and asks for `run_shell`.
2. **replace_text preview fix.** Accept: the card's diff shows removed and added rows.
3. **Transcript panel and Message.** Accept: during `delegate_async` the panel shows `question:`, tool lines and the answer within a second; a message appears as `user:` in the log and the next tool result carries the keyed `<user-message>` block; the steer route no longer returns 501.
4. **Background result card.** Accept: a finished background delegation paints a card while idle, and the next turn carries `<background-results>`.
5. **`run_cmd_bg` and `environment`.** Accept: `run_shell_bg("sleep 30; echo hi")` returns an id, `shell_output` later shows `exit 0` and `hi`, the log opens in the panel, `environment` names leela's interpreter and venvs, and `ws.shutdown` kills the process.

## Changes leela needs in ramabana and shalya

- Fixed in 0.1.37: `_record` read `.approved` on an `Ask` that only has `.answer`, so a hook rewriting a write tool's args with approvals on raised.
- `Agent.stream` drops the text `_finish` appends, so the verify line never reaches a streaming frontend. Store it as `last_verify` and expose it, or yield it as a final delta.
- Split `Approvals.request` into a `decide(name, args, force)` that applies off, rules, auto and edits, and the wait, so `Interventions.request` can reuse the decision. Pass `run_id` through.
- Move `Ui.skill_command` and the approve-mode settle onto `Agent.expand_command` and `Approvals.set_mode` so a non-CLI frontend can call them.
- Give `watch` a frontend seam, an `on_watch(target, log)` callback or event, instead of assuming panes.
- Expose background completion as an event or `Agent.on_background_done` rather than a closure inside the `background` property. `EVENTS` in shalya is a fixed tuple and would need `background_done` and `watch`.
- Forward `verify=` from leela's `Assistant.__init__`.
