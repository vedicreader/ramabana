# Embedding ramabana in a long-running host: what to add

VedicReader's Align Studio will drive ramabana from Python to run "add a work" jobs: find lawful sources, propose a text's
structure, write adapter code in a git worktree, review. A job runs in a detached Python process so it survives a web-server
restart; a web page shows its progress and puts approvals to the owner. This plan lists what ramabana 0.2.26 already gives such a
host, and what to add, in priority order. File references are to `ramabana/` at 0.2.26 (ed9ef33).

## What the host will use as it is

- `mk_agent(roots, model, approve, read_outside, host_kw, **kw)` and `Agent(cfg=, sp=, on_activity=, routing=, max_steps=,
  max_tool_calls=, subagents=, readonly=)`.
- `agent.ask()` / `agent.stream(on_registered=)` from a worker thread; `agent.cancel()`, `agent.terminate()`, `agent.close()`.
- Steering: `agent.steer(text)` (delivered with the next tool result), `agent.leftovers()`, `agent.tell(run_id, text)` for a
  sub-agent.
- `Approvals.listen(on_ask, on_answer)`, `Approvals.answer()`, rules with `always()`, `set_mode()`, plan mode.
- `Activity(on_change)`, `agent.on_plan`, `agent.use` / `agent.turn_use`, `pane.write_snapshot()`, the run `.log` files.
- `resume_session()`, the crashed-turn recovery (`recover_turns`), `claim_session()`.
- `agent.add_tool(f)` with `@writes` / `@acts` / `@summary`, `registry.on('before_tool' | 'after_tool' | ...)`.
- `agent.oneshot()`, `set_model(name, job=)`, per-job routing.

## P0: needed before the Studio's agent jobs ship

### 1. Approvals hold many requests

Today `Approvals` is a queue of one: `request()` overwrites `current` (agent.py:545) and `answer(id, ...)` only matches it
(agent.py:451-454). A background write sub-agent and the main turn asking together leave the older ask unanswerable except through
`Ask.resolve()`, which skips `on_answer`.

Add: a dict of pending asks keyed by id; `answer(id, ok, note='', ...)` resolves any of them and notifies `on_answer`;
`pending` returns all of them, oldest first; `cancel_all()` and `close()` refuse all. Keep `current` as the newest for the CLI.
Tests: two threads ask at once, both answered by id in either order, both `on_answer` callbacks fire; close refuses both.

### 2. A policy for no listener and for timeouts

Today `request()` refuses at once when nothing has called `listen()` (agent.py:547-549), and `mk_agent` passes `timeout=None`, so
an unanswered ask waits forever.

Add to `Approvals(...)` and `mk_agent(...)`: `no_listener='refuse'|'wait'` (default `refuse`, as now) and
`on_timeout='refuse'|'allow'` with `timeout=` honoured from `mk_agent` (default stays `None` there). A host that restarts can then
choose to wait for its page to reconnect. Tests: each combination.

### 3. A callable approval policy, consulted before asking

`registry.approval(fn)` is registered but never read (shalya skills.py:183-186; no `fire('approval')`), and `before_tool` runs
after the gate, inside the tool wrapper. A host needs to allow read-only calls by rule and ask for the rest, without the pane.

Add: `Approvals(policy=fn)` where `fn(name, args) -> 'allow' | 'deny' | 'ask' | None` (None falls through to modes and rules),
consulted in `decide()` before rules and modes; and wire `registry.approval(fn)` to set it, or remove the dead registration. Keep the
loop guard (`DOOM_LOOP`) above the policy. Tests: a policy that allows `run_shell` only for `rg`/`ls`/`cat` commands and asks for
everything else; the third identical call still asks.

### 4. An event for an approval that is pending

No `Act` exists until a call is approved (the gate runs before `_record`), so a host cannot show "waiting for you" in the activity
list, and the spike lost 11 minutes to an ask it could not see.

Add: when `request()` notifies, create an `Act` with `state='awaiting'` and the ask id (and the would-be tool, args, preview),
updated to `running` / refused when answered; fire `on_activity` for both. Tests: the act appears before the call runs and carries
`ask_id`.

### 5. Read-only roots

Every root is writable (shalya `Sandbox` keeps one flat list), and `read_outside` does not reach `grep`, `search_code` or
`ls recursive=True` (shalya tools.py:82-141, host.py:648-679), which is why the spike fell back to `rg` through the shell.

Add: `mk_agent(roots=..., read_roots=...)` (and `add_root(path, readonly=True)`): read tools (view, outline, grep, search_code, ls
recursive, notebooks) search write roots and read roots; write tools refuse a read root with a clear message; the system prompt names
both lists. Tests: grep finds a hit in a read root; a write there is refused; a shell `cwd` in a read root is refused for writes.

### 6. A structured result

`ask()` returns the reply string, a dict when cancelled, or a failure note, and never raises (agent.py:3140-3172); there is no
schema output, and urai's `Chat.structured` is not wired and absent on Claude.

Add: `agent.ask(prompt, schema=PydanticModelOrJsonSchema)` that registers a temporary `submit_result` tool whose parameters are the
schema, tells the model to call it once at the end, validates the payload, and returns a `TurnResult(reply, state, error, usage,
result, session, turn_id)`; `ask(..., result=True)` returns that object without a schema. `strict=True` raises `TurnFailed` on a
failed or cancelled turn and `ResultMissing` when the tool was never called. Tests with a fake backend: valid payload, invalid
payload re-asked once, missing result.

### 7. The session lock on every turn, and a session id argument

`_begin_turn` calls `claim_session()` and ignores a False result (agent.py:2240); only `resume_session` refuses a held session; the
history jsonl has no cross-process lock; the session id has no constructor argument.

Add: `Agent(session_id=...)`; `_begin_turn` raises `SessionBusy` when another live process owns the session; an `fcntl` lock
around history appends (or one history file per session). Tests: two processes, the second refused; appends from two processes
stay whole lines.

### 8. Budgets

`max_steps` and `max_tool_calls` default to unlimited for the root (`'auto'`, agent.py:3451-3467); no money or token budget.

Add: `Agent(max_cost=, max_tokens=)` per turn and per session, checked after each model step from `Usage`; on breach the turn is
cancelled with state `budget` and the reason in `problems`. The CLI keeps its defaults. Tests with a fake backend's usage.

## P1: makes jobs sturdier

### 9. A follow-up queue and unread steering

Steering arrives only with the next tool result; messages never read need `leftovers()` and a resend. Add `agent.queue(prompt)`:
prompts run in order after the current turn, and unread steering is prepended to the next queued or new turn automatically.

### 10. Cancel keeps the conversation

A detached run's backend is dropped on cancel (agent.py:3134-3137), so the next turn starts fresh and `resume_session` restores text
only (tool results clipped to 600 chars, agent.py:142-153). Keep the backend's message list (or persist full tool results per turn)
so a cancelled or crashed job resumes with full fidelity; a `resume_session(full=True)` that replays tool calls and results.

### 11. An append-only event file

For a host page that tails a job from another process: `agent.events_to(path)` writes one JSON line per event (act start/finish,
ask pending/answered, plan change, turn start/end with state and usage, steering delivered), flushed per line, rotated by size.

### 12. Safer defaults for embedding

- `mk_agent(python='kernel' | 'off')`: `run_python` today runs in the host's own process (shalya host.py:849-853).
- `mk_agent(global_skills=False)`: `~/.agents/skills` is always searched today.
- `Agent(extra_sp='...')`: an addition to the briefing without replacing it (today only `sp=` replaces it all).
- Per-job approval rules: `rules_path` defaults to `<cfg>/approvals.json`, shared by every session on that cfg; let a host pass its
  own.

## P2: nice to have

13. A local control server for a detached runner (unix socket, JSON-RPC): prompt, steer, cancel, list and answer approvals,
    subscribe to events. The Studio can do without it if items 1-4 and 11 exist, by running the agent in its own runner process and
    exposing its own control.
14. A worktree helper: `host.add_worktree(repo, branch, readonly=False)` creating the worktree and adding it as a root.

## Acceptance: one example a host can copy

`examples/embed_host.py`: builds an agent with a write root, a read root and a policy that allows read-only shell; runs a turn with
`schema=` in a worker thread; prints events from `events_to`; an ask is answered by id from another thread while a sub-agent also
asks; the process is killed mid-turn and a second process resumes the session with full fidelity; a `max_cost` budget stops a
runaway turn. Run it in CI with a fake backend, and once by hand on a real model.

## Order

1 → 2 → 3 → 4 (approvals, the Studio's first need), 6 (results), 5 (read roots), 7 (lock), 8 (budgets), then P1. Each with tests in
the notebooks and a CHANGELOG entry; release when 1-8 are in.
