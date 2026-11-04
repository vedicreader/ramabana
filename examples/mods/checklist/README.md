# checklist

`checklist` keeps a short list of items you pin, such as "update CHANGELOG" or "run the slow tests". The agent sees the open items at the start of every turn and marks them done, skipped or added through a `checklist` tool. An item pinned as a gate stops `git_commit` and `git_remote` pushes until the person settles it.

Install it by copying this folder to `~/.config/ramabana/mods/checklist/`. `ramabana mods check ~/.config/ramabana/mods/checklist` shows what it registers.

## Commands

`/check` lists the items with numbers and marks: `[ ]` open, `[x]` done, `[-]` skipped, with `!` after the mark for a gating item and a skip reason in parentheses.

`/check add TEXT` pins an item. `/check add! TEXT` pins a gating item, or makes an open item with that text gating.

`/check done N`, `/check skip N [REASON]` and `/check undo N` change item N's state. `/check rm N` removes it. `/check clear` removes the done items and keeps open and skipped ones.

`/check suggest` lists the items dhrona has learned to suggest. `/check pin K` pins suggestion K.

The status bar shows `check 2/5`, settled items (done or skipped) over all items, while the list is not empty.

## What the agent sees

Each turn, while any item is open, the mod adds the open items to the turn as context and asks the model to call the `checklist` tool when it completes, skips or adds one. The tool takes `action` (`check`, `skip` or `add`), `item` (the open item's number, its text, or a part of its text that matches only one open item, all without regard to case) and an optional `reason`.

A gating item belongs to the person. The `checklist` tool refuses `check` and `skip` on one, with a reason telling the model to ask the person to run `/check done N`. `/check done`, `/check skip` and `/check undo` still work on it.

While a gating item is open, `git_commit` and `git_remote` with `op` set to `push` are refused with the reason `checklist: ` followed by the item's text. `git_remote` fetches and pulls pass. If the saved list cannot be read, both are refused with a `checklist: ` reason saying so.

## How dhrona uses it

Each `checklist` tool call is an activity row in the session history, and each gate refusal is a refused tool call whose reason starts with `checklist: `. dhrona reads both: which items get checked or skipped, with what reasons, and which gates held a commit. From them it writes suggestions to `<config>/learned/checklist.md`, one item per line starting with `- `, at most 1500 characters. `/check suggest` reads that file, and `/check pin K` turns a suggestion into a pinned item. The mod never writes in the learned folder. With learning off, `/check suggest` says so.

## State

The items live in the mod's own store, `state.json` in the mod's home folder (the mod folder itself when it is installed as a folder), through `reg.store()`. Writes re-read the file under a file lock, so two sessions changing the list at the same moment merge instead of overwriting; a session reads its own copy of the list until its next write. When the mod has no home folder the items live in memory for the session. dhrona does not read the state file; it works from the session history, as described above.
