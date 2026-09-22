# Claude Code parity plan

Ranked by impact on daily terminal coding. Each item names the notebook it lands in, its size, and the acceptance check. Sizes: S under a day, M one to three days, L a week.

## Keep and lean on

Ramabana already exceeds Claude Code in: root sandbox with a read/write split and credential deny globs, hash-addressed edits that fail on a stale read, per-job model routing, refusals that carry a reason back to the model, read-only sub-agents by default, conversation branching (`fork`, `undo_turn`, `revise`), preflight `search_code` before the model speaks, folder monitors, vault memory with PII gating, ACP and MCP servers, and step and tool budgets.

## Top 10

1. **Diff preview and permission rules** (M, `03_agent`, `05_cli`). `preview_for` falls through to raw JSON for `replace_text` and `run_shell`. Show `diff_text(before, apply_edits(...))` for `replace_text` and command plus cwd for `run_shell`. Give `Approvals` persisted rules `(tool, glob, allow|deny)` at `<cfg>/approvals.json`, an `edits` mode (auto for editors, ask for shell, python and git writes) and an "always allow this pattern" key. Fold or delete the uncalled `policy()`. Accept: a `replace_text` approval shows a unified diff; a saved `run_shell` rule for `pytest` skips the prompt next session.

2. **Project and user instruction files** (S, `03_agent`). `CONTEXT_FILES` reads only `AGENTS.md` variants; `CLAUDE_NOTES` is exported and never applied. Add `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and a user-level `<cfg>/AGENTS.md`; append `CLAUDE_NOTES` when the turn model is a `claude/*` spec. Accept: a repo with only `CLAUDE.md` gets its rules in the briefing.

3. **Git workflow tools** (M, shalya `02_tools`, ramabana `03_agent`). Add `git_diff`, `git_log`, `git_commit`, `git_stash` beside the existing `git_status` and `git_remote`, and `/commit` and `/pr` commands that draft the message on the summary model and go through the normal write gate. Accept: `/commit` proposes a message from the staged diff and commits only after approval.

4. **Background shell and completion notices** (M, shalya `01_host`, ramabana `02_tools`, `05_cli`). `run_cmd` is synchronous with a 120 s kill. Add `run_shell_bg`, `shell_output`, `shell_stop` (kept in the host, not in `Agent.runs`); give `Background` an `on_done` that queues the answer into the next `_prepare` so `delegate_result` polling stops; ring the bell on turn end and on approval requests. Accept: a background test run reports its summary into the next turn without a poll.

5. **Verification gate before completion** (M, `03_agent`). `Agent.changes()` knows the files written this turn and nothing consumes it. Read a `verify` command from project context or `pyproject [tool.ramabana]`; in `_finish`, when files changed and no `run_shell` followed the last write, run the check behind approvals and append the result, and print a `changed:` line per turn. Accept: an edit with no test run ends with the project check's output, not a bare claim.

6. **File checkpoints and `/rewind`** (M, `03_agent`, `05_cli`). `self.before` holds pre-write text and is discarded each turn. Persist it per turn under `<cfg>/checkpoints/<session>/`; add `/rewind [TURN] [files|chat|both]` over `undo_turn` plus `host.write`, and `/branches`, `/branch NAME` for the existing fork machinery. Accept: `/rewind 3 files` restores the pre-turn text through the write gate.

7. **Hooks that can block or rewrite** (S/M, shalya `03_skills`, ramabana `02_tools`). `fire` discards hook return values. Treat a `before_tool` string return as a denial reason and a dict as replacement args; treat an `after_tool` string as the new result; add `stop` and `session_start` events and a `<cfg>/hooks.json` of shell hooks fed JSON on stdin. Accept: a hook that rejects `rm -rf` returns its reason as the tool result.

8. **Skills as slash commands** (S, `05_cli`, `03_agent`). A line starting with `/skillname args` is an unknown command today. When `command()` returns None and a skill or `<cfg>/commands/*.md` matches, send the line as a turn with the skill attached and `$ARGUMENTS` substituted. `allowed-tools` from front matter is not honoured: shalya's skill loader keeps no front matter. Accept: `/exhash fix the loop` reaches the model with the exhash skill inline.

9. **Headless mode** (S, `05_cli`). Read the prompt from stdin when not a tty; add `--json` printing reply, usage, changes and session id; warn on stderr when `--approve ask` has no tty, since every write is then refused silently. Accept: `echo prompt | ramabana --json` returns machine-readable output and a warning about refused writes.

10. **Memory without the vault** (M, `03_agent`). `memory_context` is a stub and `remember` exists only with `--vault`. Keep `<cfg>/memory/<root-hash>/MEMORY.md` capped near 4k chars in the briefing, a `#note` prefix that appends a line, and a `remember_note` tool when no vault is open. Accept: a note saved in one session appears in the next session's briefing for the same root.

## Below the fold

| Gap | Proposal | Size, notebook |
|---|---|---|
| MCP client | `<cfg>/mcp.json`; an `McpHost` wrapping server tools as `@writes`/`@acts` by annotation | L, new notebook |
| Worktree isolation | `/worktree NAME` via `git worktree add`, `host.add_root`, `delegate_async(worktree=True)` | M, `02_tools` |
| Plan mode | `/plan-mode on|off` toggling `readonly` plus `reload()`; show `plan.md()` on exit | S, `03_agent`, `05_cli` |
| Sub-agent definitions | `.agents/agents/*.md` with sp, model, tool view, `max_steps`; `delegate_search(agent=...)` | M, `02_tools` |
| Cost without backend pricing | pricing table on `ModelSpec`, computed in `Backend._usage` when cost is zero | S, `01_runtime` |
| `--continue` per folder | record roots in the session row; `--resume latest` filters by them | S, `03_agent` |

## Order

Batch one: items 2, 8, 9 (all S, single cells). Batch two: 1, 5, 4. Batch three: 3, 6, 7, 10. The fold table follows demand.
