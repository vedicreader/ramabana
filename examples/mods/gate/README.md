# gate

`gate` asks a person before selected shell commands, `git_remote` pushes, `git_commit` calls, and release turns. Copy this folder to `<config>/mods/gate/` to load it.

`/gate` shows the state and shell regexes. `/gate off` disables both gates. `/gate on` enables them. `/gate add REGEX` adds a shell regex for the session. The status segment shows `gate` while enabled.

The shell patterns cover recursive `rm`, force pushes, hard resets, `git clean -fd`, recursive `chmod`, `dd`, `mkfs`, redirection to `/dev/`, and `sudo`. Non-recursive `rm`, including `rm missing`, passes without asking. `git_remote` push and `git_commit` always ask. A release, publish, or deploy whole word in a prompt asks once with a checklist. If `ask_user` is unavailable, the gate refuses the action or turn.

Deletion previews list literal paths and file counts under open folders when available. Counts include files in subdirectories and do not follow directory symlinks. Shell expansions and inaccessible paths have unavailable counts. Git previews include the command and current branch, or `unknown` if it cannot be read.

The shell gate matches command text, not a shell syntax tree. It can miss equivalent commands and can match text that would not execute. It does not cover other tools or background shell calls. Do not use it as a security boundary.
