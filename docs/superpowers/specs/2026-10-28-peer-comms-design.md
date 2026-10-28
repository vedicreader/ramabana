# Peer talk between Claude Code and Ramabana sessions

## Why
The user runs several agent sessions on repos that depend on each other. For example, a Claude Code session works on abhyasa and sanketa, and a Ramabana session works on ramabana and leela. Abhyasa and leela both use rupaka for demos, and sanketa shows ramabana's shortcuts. Today the user carries every update between the sessions by hand, so the user is the bottleneck.

Goal: any live session, Claude Code or Ramabana, can find the other live sessions and send a message to one of them. The receiving session can act on the message, and when the user is away the sessions can work together without the user.

## Goals
- One list of live sessions that both kinds of session can read. Each row shows the session's name, kind (`claude` or `ramabana`), folders, state and id.
- Messages sent to one session. A target can be a list number, a session id, or a repo or folder name (`sanketa`).
- Two kinds of message:
  - **note**: information only ("ramabana has new shortcuts"). A note never needs approval. A note can go to all sessions.
  - **ask**: a request for work ("build a `Card` part that leela can reuse"). It gets a reply.
- The receiving session decides. By default, before it acts on an ask, it asks its own user.
- **Work together mode**, which the user turns on for each session before going to bed or going out. In this mode, the session acts on asks from its partner sessions without asking the user.
- A **morning report** of what happened while the user was away.

## Non-goals
- Talk between machines. Everything is on one Mac, for one user.
- Claude ↔ Claude talk. Claude Code already has `SendMessage` for this.
- A replacement for rishi, or a change to how Ramabana drives its own Claude backend (`rishi-claude-*`).

## Anti-goals (a failure even if it works)
- **Bad code.** Work done for another session that ignores the owning repo's rules: bloated code, too many docstrings or comments, prose that breaks the user's rules, or UI that was never checked in a real browser.
- **Loops.** Two sessions that reply to each other all night and use tokens.
- **Hidden talk.** A message the user cannot find later.
- **Edits to another session's repo.** A session asks the owner; it does not edit folders that a different live session owns.
- Tests that write to the real `~/.config/ramabana`, take window focus, or touch the user's default tmux server.

## What exists (0.2.82)
- `control.py`: each terminal session listens on `runs/<session>/control.sock` (JSON lines; `prompt, steer, cancel, asks, answer, status, events`). `peers_of(agent)` finds live sessions by globbing those sockets. `tell` sends `steer` or `prompt` and reads the reply from `events.jsonl` with `await_reply`. `/peers`, `/tell N` and the `peers()`/`tell()` tools use it.
- Today a peer's `prompt` asks the **sender's** user. This design moves that approval to the **receiver**.
- Extensions (`cfg/extensions/*.py`, `setup(reg)`) and `hooks.json` shell hooks are available, but the core of this design goes in `nbs/20_control.ipynb`, because the user wants `ramabana tell` in control.

## Design

### 1. The session list
- Ramabana sessions stay as they are: the socket plus `status`. `status` gains `folders` (all roots), not only `folder` (`roots[0]`).
- Sessions of other agents (Claude Code first, then Codex and others, see §5) register a file `cfg/peers/<kind>-<id>.json`: `{kind, session, name, folders, pid, inbox, at, together}`. The agent's session-start hook writes it, and its session-end hook removes it. When the `pid` is gone, the row is stale and the next read removes it.
- `peers_of` returns all kinds, with a `kind` field. `peers()`, `/peers` and the new CLI all show all of them.
- `name` is the same short label for each kind: the first folder, then the model or the kind.
- My call, on folders: a registered session starts with the git root of its `cwd` (or the `cwd`). `ramabana peers --add-folder PATH` adds more; the peer-work skill tells an agent to run it after `/add-dir`.
- My call, on targets: a repo name that matches more than one session is an error that lists the matches, so the sender picks one. `--all` is the only broadcast.

### 2. The message
One envelope for both directions:
`{id, thread, kind: note|ask|reply, from: {kind, session, name}, to, repo, text, hops, at}`, and on a reply also `changes` (files, commits) and `proof` (test command and its result, screenshot paths).
- `thread` connects an ask to its replies. `hops` goes up by one on each reply in a thread. When it reaches `HOP_MAX` (default 6), the receiver refuses to send another message and records the refusal.
- My call, on loops across threads: in work together mode, each session has a budget of `PEER_BUDGET` messages sent (default 40, notes included) and turns started by peers (default 20). When a session reaches its budget, it stops, sends one note saying so, and the stop goes on the user's action list.
- My call, on proof: the replier fills `changes` and `proof`. The report checks `changes` against `git log` in the replier's folders since the mode started; a reply that says "done" with no `proof` shows as "not proven".
- Each envelope is appended to `cfg/peers/log.jsonl`, the one shared log. The morning report reads this log.

### 3. The CLI (`ramabana peers`, `ramabana tell`, `ramabana inbox`, `ramabana together`, `ramabana report`)
Ramabana uses these as tools and slash commands. Claude Code uses them from Bash.
- `ramabana peers [--ids]`: the numbered list.
- `ramabana tell TARGET TEXT [--ask] [--all] [--repo R] [--thread T] [--wait N]`. The default kind is `note`. `--all` sends a note to every session. With `--wait`, an ask waits for the reply and prints it.
- `ramabana inbox [--wait N] [--session ID]`: print the unread messages and mark them read. With `--wait`, block until a message comes or `N` seconds pass, then exit.
- `ramabana together on|off [--with A,B] [--until HH:MM] [--session ID]`.
- `ramabana report [--since T]`: see §7.
- How the CLI knows the id of the Claude session that calls it: from `$CLAUDE_CODE_SESSION_ID`. Claude Code sets it in Bash and hook subprocesses, and it changes on `/clear`. When it is set and `--session` is not given, the CLI acts as that Claude session (sender, inbox, together).

### 4. Delivery to a Ramabana session
- A new control method `message(envelope)`. Ramabana handles each kind as follows:
  - **note**: show it in the UI. If a turn is running, steer it in; if not, keep it as context for the next turn.
  - **ask**, in work together mode with the sender as a partner: start or queue a turn, as `prompt` does now.
  - **ask**, in any other case: show an approval in the **receiver's** UI through `agent.approvals`. If the user approves, the turn starts. If the user is away, the ask waits.
- My call, on waiting: every message is also written to the receiver's inbox file `cfg/peers/ramabana-<id>.inbox.jsonl`, the same as for other agents. A peer ask does not time out with `DFLT_TIMEOUT`; it stays pending in the inbox and shows again at the next key press or when the session resumes. A message to a session that is not live fails at once, and the sender is told.
- A reply goes back through the same envelope. Ramabana sends it after the turn ends, from an `after_turn` hook, with the turn's reply text.
- The existing `prompt`/`steer` methods stay for older callers.

### 5. Delivery to Claude Code, Codex and other agents
All of this ships in the ramabana repo. The user installs it with `ramabana setup peers [--agent claude|codex|...]`.
- **Adapters.** One small adapter for each agent kind, in the notebook. It holds: the agent's config file and the hook block to merge into it, the environment variable that gives the session id, the skill or instruction file to install, and how the agent is woken. `ramabana peer-hook <kind> <event>` is the one entry point that every hook calls, so the logic is shared.
- **`ramabana setup peers`** shows the diff of each config file it would change (for Claude Code, `~/.claude/settings.json` and `~/.claude/skills/peer-work/SKILL.md`), and writes only when the user confirms. `--remove` takes the block out again. `ramabana --doctor` reports which adapters are installed.
- **Claude Code** is the first adapter, as described below.
- **Codex and others**: the builder checks what each agent supports (hooks, a session id variable, a way to wake). An agent without hooks gets the fallback: the CLI to send, and an instruction in its `AGENTS.md`-style file to run `ramabana inbox` at the start of each turn. Such a session cannot be woken while idle, and `ramabana peers` marks it so.

Claude Code adapter:
- **Inbox**: `cfg/peers/claude-<id>.inbox.jsonl`. `ramabana tell` appends to it.
- **`UserPromptSubmit`**: add the unread messages to the context of the prompt. Also turn off work together mode, because the user is back. If the mode was on, show the morning report.
- **`Stop`** (sync): if there are unread messages, return `{"decision": "block", "reason": <messages>}`, so Claude goes on and handles them. Claude Code stops a block chain after 8 blocks in a row (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), and the hop limit stops loops before that.
- **Waking an idle session**: a second `Stop` hook, `async: true, asyncRewake: true`, runs `ramabana peer-hook wait`. It blocks until a message comes, then exits with code 2 and the messages on stderr. That wakes Claude even when it is idle (documented in hooks.md, "Run hooks in the background"). Async hooks have no timeout. Only one waiter runs for each session: a lock file `claude-<id>.wait` holds the waiter's pid, and a new waiter exits at once while the old one lives. The waiter exits when the session's registration file is gone (`SessionEnd`).
- My call: the waiter runs in both modes. Outside work together mode, a woken Claude only shows the message and, for an ask, asks the user. That costs one short turn and keeps notes timely.
- The Claude side of approval is a rule, not a gate. The hook text tells Claude to ask the user before it acts on an ask, unless work together mode is on with that sender.
- My call, on other sessions' folders: this is enforced, not only a rule. A `PreToolUse` hook on Edit, Write and NotebookEdit refuses a path inside a folder that a different live session holds and this session does not. On Ramabana, the same check is an `Approvals` policy. A folder that two sessions both hold is open to both.

### 6. Work together mode and code quality
- **Scope**: per session, optionally only with named partners (`--with abhyasa,leela`).
- **Tool permissions do not change** (user's decision). Work together mode only removes the "may I take this ask?" step. Each session keeps its own permission mode: Ramabana's approval mode (`ask`, `edits`, `auto`), and Claude Code's permission mode. On auto, a session does what it normally does on auto. On a stricter mode, a step that needs approval waits, and the morning report lists it on the action list. `ramabana together on` prints each partner's current mode, so the user can see before leaving which sessions will stop at the first approval.
- **End**: at `--until`, when the user types in that session (a Ramabana key press, or Claude's `UserPromptSubmit`), or with `off`. Without `--until`, the mode ends after 12 h.
- **The peer-work skill**, `peer-work`, is the protocol text that both sides read. Ramabana registers it as a skill. Claude gets it from the hook context and from a Claude skill file. It says:
  1. Before you write code in a repo, read that repo's rules: `CLAUDE.md`/`AGENTS.md`, its skills (for example ramabana's `coding_patterns`, vedicreader's lego block pattern) and the user's general rules (functional style, short and efficient code, one-line docstrings, no comments that are not needed, STE prose).
  2. For an ask that adds code another repo will own, agree on the shape with the owner first: which existing blocks to use, where the code goes, and the API. The owning repo has the final say.
  3. Do not edit folders that another live session owns. Ask the owner.
  4. "Done" needs proof: the test command and its output, and for UI, a check in Chrome for Testing with the screenshot path. No proof means the work is not done.
  5. The owner reviews the diff against its rules. If the code is bloated or off-pattern, the owner asks for changes before it accepts the work.
- Each ask carries `repo` so that the receiver knows whose rules apply.

### 7. The morning report
`ramabana report --since <mode start>` builds the report from `log.jsonl` and each session's `events.jsonl`:
- **A table**, one row per thread: who asked, who did the work, what changed (files and commits), proof (tests, browser check), and state.
- **Simple examples**: one plain sentence per change. For example: "Ramabana added ⌥T for tell. Sanketa now shows it."
- **The user's action list**: each item says what to do and where. For example: "Approve abhyasa's `Card` part for leela: read 40 lines in `rupaka/card.py`."
- **A glossary** of the terms used: peer, note, ask, thread, hop, work together mode, proof.
- The table and the glossary come from the code. The examples and the action list come from the routed `summary` job (`Agent.oneshot`) and follow the STE prose rules.
- My call, on timing: the report is built when the mode ends at `--until` or after 12 h, by the waiter or Ramabana process that sees it end, and saved as `cfg/peers/reports/<date>.md`. When the user comes back (§5 `UserPromptSubmit`; the first Ramabana key press), the session shows the saved file. Hooks make no model calls. If the user comes back before the report is built, the hook shows the table and the glossary, and tells the agent to run `ramabana report` for the rest.
- `ramabana report` gives it on demand.

## Testing
- In notebook test cells, with a temporary `cfg`. Never the real `~/.config/ramabana`, and no tmux, browser or window focus.
- Tests cover:
  - `peers_of` with fake Claude registration files: live pid, dead pid, and the `kind` field.
  - Targets by number, by id and by repo name.
  - `message` over a real `Control` socket on a `ScriptedBackend` agent: a note steers, an ask asks for approval by default, and an ask starts a turn in work together mode.
  - Hop limit; work together mode expiry and the end on user input.
  - `inbox --wait` exits on a message.
  - `peer-hook` input and output for `UserPromptSubmit` and `Stop` (fixture JSON in, JSON out).
  - Report table and glossary from a fixture log, with the `summary` job stubbed.
- `ramabana setup peers` on a temporary home: the diff, the confirmed write, `--remove`, and a second run that changes nothing.
- The folder guard: a write inside another live session's folder is refused; a shared folder is allowed.
- Budget and hop limits stop a scripted pair of sessions that reply to each other forever.

## Open items for the builder
- Hook facts (code.claude.com/docs/en/hooks.md, read 2026-10-28): `SessionStart` input has `session_id, cwd, source` (`startup|resume|clear|compact|fork`) and can return `hookSpecificOutput.additionalContext`. `UserPromptSubmit` returns `hookSpecificOutput.additionalContext` (default timeout 30 s; check the exact shape in the docs). `SessionEnd` has a 1.5 s budget, so it only removes files. Sync hooks stay fast: no network, no model calls.
- The UI text for notes and approvals in Ramabana's terminal.
