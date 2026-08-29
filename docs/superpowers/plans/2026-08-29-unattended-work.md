# Work that outlives the turn that started it

> **Decisions taken on 2026-08-29.** Async delegation is in. Approvals reach background work.
> The CLI gets a control for the approvals mode. pobblebonk owns the clock and drives Ramabana
> from outside, so no scheduler goes in the agent core.

The goal: a task can outlive the turn that started it, and the writes it wants are gated by
someone who is there to answer.

Four tasks. Task 1 is the capability, Task 2 is what makes it safe, Task 3 is what makes it
usable, Task 4 is what makes it fire with nobody watching. Task 1 does not ship without Task 2,
and neither does Task 4.

## State on 2026-08-29

Measured from the working tree. A later session re-measures rather than trusts this.

- `Run` (`runtime.py`) is a full lifecycle tree: pending, running, cancelling, cancelled,
  detached, terminated, failed. Parent and child, grace, `wait`, `detach`, `terminate`,
  `request_cancel`, and `dict()` for the whole subtree. It lives in `_run_store(self)`, a dict on
  the agent, and does not survive the process.
- `delegate` (`tools.py`) already takes a pre-registered `run=` and already threads `approve=`
  into `backend.spawn`. It registers the child, calls `run.start()`, `run.attach(sub)`, and
  `run.finish()`. The only reason it blocks is that it calls `sub.send` inline and returns the
  text.
- `delegate_search` blocks. `delegate_parallel` runs a pool and joins. Neither returns a handle.
- `Approvals` (`agent.py`) is the queue of one: `current`, `pending`, `answer(id, ok, ...)`, a
  `_lock`, per-frontend `listen`, and a timeout. `mode` is set once, from the CLI's `--approve`.
- `poll_watches` and `poll_monitors` are both called from `_prepare` (`agent.py:1543`), so
  nothing fires unless a turn starts.

### Keymap audit

Required before proposing a shortcut. Taken in normal mode: `ctrl+a`, `ctrl+c`, `ctrl+d`,
`ctrl+e`, `ctrl+k`, `ctrl+n`, `ctrl+o`, `ctrl+p`, `ctrl+r`, `ctrl+t`, `ctrl+u`, `ctrl+v`,
`ctrl+w`, `ctrl+y`, and `alt+1`..`alt+9`. Taken while an ask is pending: `y`, `n`, `a`, `ctrl+y`,
`ctrl+c`. Free and safe: `ctrl+g`, `ctrl+b`, `ctrl+f`, `ctrl+l`, `ctrl+x`. `ctrl+s` is not safe, because
terminals still use it for flow control.

`SURFACE_COMMANDS` carries no approvals command. The only in-session change to the mode is `a` during a
pending ask. It sets `mode='auto'` permanently, under the comment *only an approval may turn the
policy off*. There is no way back to `ask`, and no way to reach `off` at all.

## Task 1: delegation that returns a handle

`delegate` needs no change. What is missing is a caller that does not join.

- [ ] `delegate_async(question, skills='') -> run_id`. Register the child `Run` on the parent,
      start `delegate(..., run=child)` on a daemon thread, return `child.id`. The tool returns
      as soon as the run is registered, never before: a handle for work that was not accepted is
      a lie the model will act on.
- [ ] `delegate_status(run_id='')` reads `Run.dict()` through the existing `runs()`. Empty
      `run_id` lists every live child of the current session.
- [ ] `delegate_result(run_id)` returns the answer for a terminal run, or says it is still
      running. Results live in a bounded dict beside `_run_store`, keyed by run id.
- [ ] `delegate_cancel(run_id)` calls the existing `request_cancel()`.
- [ ] Add all four to `NO_SUB`. A sub-agent that can spawn background sub-agents is a fork bomb
      with a language model in it.
- [ ] A concurrency ceiling. `Routing` picks the sub-agent model and nothing caps how many run
      at once. One semaphore, sized from a new `max_async` setting.

**Failure and recovery states.** A run that fails keeps `state='failed'` and its error text is
what `delegate_result` returns. A run cancelled mid-flight returns the `_stopped` text `delegate`
already produces. A result nobody collected before the session ended is lost. That is the honest
answer until `Run` is persisted, and `delegate_status` says it rather than implying a result is
still coming.

## Task 2: approvals for work nobody is watching

The gate already reaches sub-agents: `subagent_tools._approve()` hands the session's `approve`
callable to `delegate` when sub-agent writes are on. Two things break once delegation is async.

- **The queue of one becomes a queue of many.** Several background runs each wanting a write
  serialise on `Approvals.current`, and each waits out the full timeout in turn. The queue needs
  to be a queue, or background writes need to refuse rather than wait.
- **Nobody is at the terminal.** The parent turn has ended. An ask raised by a background run has
  no one to answer it, so it times out, and a timeout that reads as a refusal is the right answer
  only if that was the intent rather than an accident.

- [ ] A background run defaults to refusing writes, whatever the session mode. Opting in is
      explicit and per call: `delegate_async(..., writes=True)`.
- [ ] An ask raised with no listener registered (`Approvals.listeners == 0`) resolves as a
      refusal immediately rather than waiting out the timeout, and says which run asked.
- [ ] `Ask` carries the `run_id` that raised it, so a frontend can say who is asking. Today the
      pending ask is anonymous, which was fine when only the foreground turn could raise one.
- [ ] Every pending ask a background run raised is refused when the session ends.

## Task 3: changing the mode from the CLI

The code already holds an invariant worth keeping: the policy only loosens by way of an actual
approval. A bare keystroke that turns approvals off would break it, and it is the kind of key
someone hits by accident. So the two directions get different controls.

- [ ] `ctrl+g` tightens one step: `auto` to `ask`, `ask` to `off`. One keystroke, always safe,
      never needs confirming. Shown in `HELP` under `approve`.
- [ ] `/approve ask|auto|off` is the only way to loosen. Typed, explicit, and it says in the
      transcript what changed and when. Add `approve` to `SURFACE_COMMANDS`.
- [ ] The status bar shows the current mode. `Ui` already renders `agent.status()`, which carries
      `budget` and `tool_budget`. The approvals mode belongs beside them.
- [ ] `a` during a pending ask keeps its meaning and keeps setting `mode='auto'`. It is an
      approval, so the invariant holds.

## Task 4: the tick, through pobblebonk

**Decided.** pobblebonk drives Ramabana from outside. Ramabana gains one entry point and no
scheduler. The reasoning is in what pobblebonk already is, read on 2026-08-29.

`heartbeat.install(cmd)` writes a launcher to `~/.pobblebonk/pobblebonk.sh` and registers it with
cron, launchd or `schtasks`, whichever this machine has, to run every 60 seconds. That is an
operating-system job, not a thread. It fires with no session open and it survives a reboot.
`Pob` is a honker database over SQLite. It holds the schedules, a fire queue with retries and
exponential backoff, a `pob_items` work list with dedup keys, and a notes stream that remembers
a read offset per reader.

So the two halves never talk directly. They share a database.

- [ ] A `ramabana-tick` console entry point. It opens the `Pob`, calls `tick()`, and returns. The
      callbacks registered under `Pob.on` are what poll watches and check folders.
- [ ] `_prepare` drains `Pob` notes with the session id as the reader, beside the `Monitors.drain()`
      it already does. A live session picks up what the beat found without the beat reaching into
      it.
- [ ] pobblebonk is an optional extra, `ramabana[cron]`. honker is not installed here today, so
      this is a new dependency chain and does not belong in the base install.
- [ ] `Monitors.pending` is backed by the notes stream when pobblebonk is present, and stays the
      deque when it is not. Same degradation the host capability groups already use.

**Why not a thread in the agent.** A scheduler in the core is inherited by every frontend, and
Leela would carry one it never asked for. An entry point is the smaller commitment, and it is the
only shape that runs when no session is open, which was the point.

**What the beat's environment is.** `launcher()` writes `#!/bin/sh` with a bare `exec`, and cron
gives it almost nothing: no PATH from a shell profile, no venv, no API keys. The entry point has
to work from that or fail loudly, and its only output goes to `~/.pobblebonk/pobblebonk.log`.
Test it under `env -i` before believing it works.

**Task 2 is the hard prerequisite.** A beat that starts a turn is an unattended agent holding
write tools with nobody registered to answer an approval. Task 4 does not ship first.

`catchup='once'` is the right default for a watch. A machine off for a week should fire the
latest missed reminder, not four hundred of them, and pobblebonk already has that policy.

### What this lets Ramabana retire

Not in this plan, but worth recording. `Monitors.pending` (`maxlen=20`, oldest dropped, gone on
exit) and `Monitors.drain()` are the lossy version of `Pob.stream` and `Pob.drain(reader)`.
`push`/`items`/`used` is a durable work list Ramabana has no equivalent of. An async
delegation result could live there instead of in the bounded dict Task 1 proposes. Two duration parsers now exist across the family. `monitor.secs` wraps
vishalakshi's. pobblebonk's also takes `w`, `M`, `y` and compound forms like `1h30m`.

## Tests

Notebook test cells in `nbs/03_agent.ipynb` for anything with a public API, per the house
division. The concurrency and lifecycle contracts go in `tests/`. They are the wrong shape for a
readable page.

- `delegate_async` returns only after the child run is registered, and the id it returns appears
  in `runs()` before the tool returns.
- A cancelled async run reaches a terminal state and its worker stops, with no accepted-work
  event after the cancel.
- `delegate_status` on an unknown id says so rather than raising.
- The concurrency ceiling holds: N+1 async delegations with a ceiling of N leaves one queued.
- A background run refuses a write by default, and performs one when `writes=True`.
- An ask with no listener refuses at once rather than waiting out the timeout.
- `ctrl+g` tightens and never loosens, from each of the three modes.
- `/approve` loosens, and the transcript records the change.
- `ramabana-tick` runs under `env -i` and reports why rather than dying silently.
- A session drains a note the beat wrote, once, and a second session with its own reader id
  drains the same note.
