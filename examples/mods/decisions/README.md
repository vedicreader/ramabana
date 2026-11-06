# decisions

`decisions` keeps a log of the decisions you have made, the questions still waiting for you, and the items you have put on hold. The log is shown in the right-hand pane, in four sections:

| Section | Shows | Colour | Kept for |
|---|---|---|---|
| Needs your decision | open questions | yellow | the session |
| Decide later | open questions on hold | aqua | the folder |
| Build later | decided items whose work is on hold | blue | the folder |
| Decided | decisions made | green | the session |

Each session has its own list of open and decided items. `/resume` shows the list of the session it resumes. Items on hold belong to the folder: every session started in the same folder shows them. The folder is the first folder the session has open.

Install it by copying this folder to `~/.config/ramabana/mods/decisions/`. `ramabana mods check ~/.config/ramabana/mods/decisions` shows what it registers. The sections need shalya 0.1.30 or later and the `now` pane open.

## Commands

`/decide` lists the log with numbers. A decided item shows its choice after `->`. An open question older than one hour shows its age, such as `· 2h` or `· 3d`.

`/decide ? QUESTION` adds an open question. `/decide DECISION` logs a new decision that is already made. It does not change the open questions.

`/decide done N [CHOICE]` marks item N decided, with an optional choice. `/decide undo N` makes item N open again and removes its choice. `/decide edit N TEXT` replaces the wording of item N. `/decide drop N` removes item N. `/decide clear`, with nothing after it, removes the decided items of the session and keeps everything else. Any other text after `/decide` is logged as a decision. For example, `/decide drop the old API` logs "drop the old API".

`/decide park N UNTIL` puts item N on hold until the condition `UNTIL` is met, for example `/decide park 3 Leela 0.1.22 ships`. An open question goes to "Decide later". A decided item goes to "Build later". The item gets a number that starts with `h`, such as `h2`, and its row ends with `· until UNTIL`. `/decide park hN UNTIL` replaces the condition.

`/decide resume hN` takes item hN off hold. It returns to the current session as a new item, open or decided as it was. `/decide done hN [CHOICE]` returns it decided, with the choice. `/decide undo hN` returns it open. `/decide edit hN TEXT` and `/decide drop hN` change or remove it in place.

Item numbers never change. A removed item keeps its number, and no later item takes it. An item moved on hold keeps its session number hidden, so the numbers after it do not move.

The status bar shows `decide 2` while the session has two open questions. It shows nothing when it has none.

## What the agent sees

The mod gives the agent a `decision` tool. The tool takes `action`, `question`, `choice` and `text`. `ask` adds an open question. `record` settles the open question that `question` names, by number, by exact text or by a part of its text that matches only one open question, without regard to case. When `question` is text that names no open question, `record` logs it as a new decision. `record` with an `h` number returns that item decided. `list` returns the log.

`edit`, `reopen`, `park`, `resume` and `drop` take an item number in `question`. `edit` replaces the wording with `text`, the choice with `choice`, or both. `edit` refuses a choice for an open question. `reopen` makes a decided item open again and removes its choice. `park` puts the item on hold, with the condition in `text`, and refuses an empty condition. `resume` takes an `h` item off hold. `drop` removes the item.

Each turn, the mod adds context to the turn. The context tells the agent to call `ask` when it puts a choice to you and `record` when a choice is settled. It tells the agent to call `park` when a question waits on something else or the work for a decision is put off, and not to act on an item on hold. It tells the agent that item numbers never change, and to fix an item with `edit`, `reopen` or `drop`. It lists the open questions, the 20 most recent decisions and every item on hold in the folder. The mod adds the list again on every turn, so the agent still sees it after the conversation is compacted.

The agent logs a question only when it calls the tool. A choice that the agent asks in its reply text without a `decision` call is not in the log. Add it yourself with `/decide ? QUESTION`.

## State

The log lives in the mod's own store, `state.json` in the mod's home folder, through `reg.store()`. The store keeps one list for each session id under `sessions`, and one list of items on hold for each folder under `folders`. Each item records the time it was added in `at`. A removed item stays in its list with the state `dropped`. A session item moved on hold stays in the session list with the state `held`. The pane, `/decide` and the agent show neither. Writes re-read the file under a file lock. When the saved file cannot be read, `/decide` says so and names the file.
