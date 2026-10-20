"""Diagnose a failure, a misbehaving tool, or Ramabana itself.

Read this before explaining why something failed: a test, a command, a scheduled job, a sub-agent, one of your own tools, or Ramabana itself.

## Find the root cause

1. Read the raw error first. Open the failing component's own record (its log, summary file or transcript) and quote the line that names the failure. A count such as "3 failed" points to that record. It is not the cause.
2. Reproduce the failure in the environment it ran in. A scheduled job does not run in your shell, so rerun the failing step with the scheduler's environment before blaming or clearing it.
3. Check a claim about code in that code before making it. "X has no timeout" and "Y already writes Z" are both claims; read or `grep` the code first. Check the version that ran as well as the checkout, because an installed package can predate a fix in its repository.
4. Name the cause and the evidence for it before changing anything. A fix that cannot be tied to the quoted error is a guess, and a workaround leaves the cause in place for the next run.
5. When an earlier claim turns out to be wrong, say so in the reply.

## A tool that misbehaves

A result that contradicts what you have already seen is a tool fault until shown otherwise. Examples:

- `grep` or `search_code` reports no matches for text you have just read.
- `ls` lists nothing in a folder that exists.
- A schema reaches a model without the fields you declared.
- The user refers to a message you never received.
- A tool reports success and the file or state is unchanged.

Confirm the fault once by a second route, such as `rg` through `run_shell`, or `view_file`. Do not explain it away as how the tool is meant to work unless its description says so. Then:

- record it with `remember`, with `component='tool'` and the call and its result as `evidence`
- say in the reply, beside the work it affected, which tool failed and how
- carry on by the second route

The fault belongs to the harness and is fixed there. The second route keeps this turn going and nothing more.

A sub-agent whose answer says its tool-call budget ran out has returned part of an answer, and its saved answer names what it did not read. Delegate that remainder as narrower questions, or read it yourself, before relying on anything in the gap.

## Where Ramabana keeps its own state

The running code is the installed package. With the interpreter that "On this machine" lists as this process, `python -c 'import ramabana; print(ramabana.__file__, ramabana.__version__)'` names it, and `uv tool list` shows the installed tool's version. A source checkout, if the user has one, is an nbdev repository whose notebooks under `nbs/` are the source. A fix goes there, and the running copy changes only once a release is installed. An editable install runs the checkout's code, but its entry points (`pyskills`, `ramabana.ticks`, scripts) change only on reinstall.

The config folder is `~/.config/ramabana` unless `--cfg` names another:

- `config.toml` holds models, jobs and settings, and `models.json` the saved model aliases.
- `agent-history.jsonl` has one line per finished turn, with its model, usage, error and the lines the user sent while it ran (`steered`). A tool result over 600 characters is clipped there; the whole result is in `agent-details/<session>.jsonl`, named by the row's `details`.
- `runs/<session>/` has one folder per session. `run_<id>.log` is one run's transcript, the turn's or a sub-agent's. `answer_<id>.txt` is a sub-agent's whole answer. `stderr.log` is the process's error output, where a backend crash can appear and nowhere else. `start.json` records each open folder's repository state at the first turn.
- `learned/` is a git repository of the rules, skills and extensions that learning keeps.

A turn on a Claude model runs through Claude Code. Its transcripts are under `~/.claude/projects/`, in the folder named after `~/.rishi-claude`, one `.jsonl` per conversation, sub-agents included. Each holds the system prompt, model, effort and every tool result exactly as the model received them.

The beat runs scheduled jobs while no session is open:

- `ramabana-tick` runs one beat, and `ramabana-tick --install --every 300` schedules it and prints the `PATH` each beat runs on.
- `~/.pobblebonk/ramabana.sh` is the launcher the scheduler starts, `~/.pobblebonk/ramabana.log` holds its output, and `~/.pobblebonk/pob.db` holds the schedules, their fires and the notes a session shows inside `<beat>`.
- The scheduler entry is `~/Library/LaunchAgents/ramabana.plist` on macOS, a line in the user crontab on Linux, and a Task Scheduler task named `ramabana` on Windows.
- Dhrona's nightly batch writes `~/.cache/dhrona/nightly/<time>/summary.json`, one row per round with its error, beside one folder per round.

## A scheduled job that fails

launchd and cron start a job with `PATH=/usr/bin:/bin` and none of the exports in a shell profile. When a beat fails with "not found", "not on PATH" or a missing key:

1. Read the launcher with `cat ~/.pobblebonk/ramabana.sh`. Since Ramabana 0.2.52 it starts with `/usr/bin/env PATH=…`, the `PATH` of the shell that installed it.
2. Read what the scheduler gives it: `launchctl print gui/$(id -u)/ramabana` on macOS shows its environment, and `crontab -l` on Linux.
3. Reproduce it: `env -i HOME="$HOME" PATH='<that PATH>' /bin/sh -c 'command -v claude git-lfs uv'`.
4. Running `ramabana-tick --install` again from a shell that finds the tools rewrites the launcher with that shell's `PATH`. A key exported in a shell profile still does not reach the beat.

Docs: https://vedicreader.github.io/ramabana/debugging.html.md"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/22_debugging.ipynb.

# %% auto #0
__all__ = []

# %% ../nbs/22_debugging.ipynb #dbg00005
__all__ = []
