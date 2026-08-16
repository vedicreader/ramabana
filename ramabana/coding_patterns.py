"""Answer.AI coding standards adapted to Ramabana's tools and nbdev workflow.

Read this before writing, reviewing, refactoring, or assessing code. These are Answer.AI's coding standards adapted to Ramabana's tools and nbdev workflow.

## Improve shared tooling

A finished task helps once. A better tool helps every later task, every later session and every agent, and ergonomics count as much as capability. Most code you have read was written by people who put up with tool friction rather than fix it, so the workaround is your default. Here the tools are ours and one edit away. When repository-owned tooling grates, fix it or say so. Never quietly work around it, and do not expand the current task without the user's agreement.

## Read before writing

Use `search_code` before writing non-trivial code: the answer or the established pattern is usually already in the repository or an installed package. Read the exact source before editing it. Use `grep` for exhaustive literal audits such as call sites and renames. Match the surrounding design unless the request is specifically to change it.

## Every construct must earn its place

Readers assume everything present is necessary. Seeing `str(x)` on something already a `str`, they stop and wonder what subtle thing it guards against, and when the answer is nothing they paid for a mystery with no payoff. The same goes for defensive copies, speculative exception handling, redundant coercions, unused parameters, abstractions and compatibility branches. Know why a construct is needed before adding it, and leave it out when you cannot say. The cost doubles in nbdev projects, where the examples are the documentation.

Knowing why a construct is needed does not mean waiting for someone to ask for it. A user who finds a gap concludes the library cannot do it and moves on. Judge a library feature by whether the design calls for it and users would expect it.

Comments state constraints the code cannot express. Never write a comment to say where a change came from, what the next line does, or why the change is correct: that is talking to the reviewer rather than to the next reader, and it is noise the moment the change is merged. Add type hints, docstrings and abstractions only where they improve the public contract or the surrounding code consistently uses them. Prefer concise readable code over verbose enterprise boilerplate.

Make the requested change and no unrelated cleanup. Never discard edits already in the working tree.

## Prefer the fastcore ecosystem

When choosing dependencies, first check whether `fastcore` or another existing project dependency already provides the capability. Do not add a dependency where the repository already has an adequate primitive, and do not hand-roll what a dependency already does.

## Plain commands are the contract

The bare invocation is the contract: `pytest -q`, `nbdev-export`. Project configuration exists precisely so the plain command does the right thing, and then every invocation is short, identical and instantly readable. Use the command the repository documents in its README, `pyproject.toml` or Makefile.

A flag, redirect or pipe states that this one call has a requirement the defaults do not cover, and used that way it carries information: the reader stops, asks why, and there is an answer. Sprinkled defensively on every call, decorations destroy that signal. Every command looks exceptional so none is, and the one deliberate flag is indistinguishable from habit. Transcripts compound the damage, since each decorated call teaches later calls to decorate too.

- Wanting the same flag on every run means a missing configuration line. Promote it and go back to the bare command: `pytest --timeout 300` on every run becomes `timeout = 300` under `[tool.pytest.ini_options]`.
- Do not check-then-apply when applying is the goal. Apply formatters when formatting is the goal, and reserve check-only modes for final verification and CI.
- Run commands and read their complete output. Never pipe diagnostics through `head`, `tail` or any filter that hides failures: the truncation is decided before the output exists, and it hides exactly the surprises worth seeing. Never merge stderr into stdout with `2>&1`; separated, a crash is unmissable.
- Where output genuinely cannot come back inline, redirect stdout and stderr to separate files and read both.
- A real one-off requirement gets its flag once, with the reason stated alongside, and disappears again on the next call.

## Preserve docments and delegation

Docments are trailing parameter comments used as API documentation, and they are the house signature style here. Never remove them while refactoring. For a signature with docments or many parameters, keep the opening parenthesis on the definition line, put one parameter on each indented line, and put the closing `):` alone at definition indentation.

Where `**kwargs` passes through to a known callable with useful named parameters, use `@delegates(callee)` and name the collector `kwargs`, which is what `delegates` requires. Do not use `@delegates` where the callee itself exposes only `**kwargs`.

## Raw strings by default

Write any non-trivial string literal as a raw string: regexes, prompt and skill text, code or markup inside strings, paths with escapes, and anything multi-line. In a plain string a stray escape -- backslash-n, backslash-d -- either errors or silently corrupts, and each miss costs a round trip to diagnose and another to fix. The `r` costs nothing when no escapes are present, so make it the default rather than the exception.

The exception is a skill body, which is an exported markdown cell and reaches the module as a plain docstring that nbdev writes without the `r`. Spell escapes out in words there rather than showing them literally.

## Tests earn their place

All code has writing, maintenance and readability costs, and tests most of all: every test has to be kept passing forever, is read by every future contributor, and has to be revised whenever the behaviour it pins changes. Never write a test as a reflex, and do not aim anywhere near full coverage. A test earns its place only when one of three things is true.

- It documents an idea. In nbdev notebooks the examples are the documentation.
- The logic is intricate enough that you had to think carefully to get it right: edge cases, parsing, arithmetic, tricky conditionals, the places a future change could silently break it.
- The code assumes something about an external system, such as a file format, an API's response shape or another tool's behaviour, that could change one day and that we want to hear about when it does. These have to exercise the real thing, because a mock merely restates our assumption.

Wiring and orchestration get no tests: re-exports, delegations, one-line glue, and functions that only sequence calls to other tools. A test there asserts that Python works and pins down internals we may want to change. The strong tell is a test that needs recording fakes or mock collaborators to reach the code, which tests a transcript of the implementation rather than logic. Extract the logic into a small pure function and test that, or do not test at all.

For a behaviour change, work red-green: write the test first, run it to see it fail, make the change, run it again to see it pass. A regression test has to fail for the reported bug before the fix and pass after it. In notebooks there are no separate test cells, so the red-green check applies to the assertion you actually added or revised.

- Prefer as few tests as possible. One test that walks through many checks is more readable and faster than many small ones.
- A check worth keeping goes in a test file or a notebook cell, never left as an ad-hoc command. In a notebook the checks made while exploring often are the narrative, so they stay as example cells.
- Assert the logic, not incidentals. Check what the behaviour guarantees, never byte-exact renderings, exact reprs or field order. A test comparing a whole output string locks in formatting decisions that were never the point. Never use a test to lock in behaviour unless that exact behaviour is part of the contract.
- Do not run slow or network-touching suites until finishing a session, or after a change likely to affect them.

In nbdev projects the notebook is source, documentation, examples and tests at once. Edit the source notebook rather than the generated Python, preserve docments and explanatory structure, export with the project's nbdev command, and run the documented tests.

## Configuration and versioning

Read from standard locations rather than duplicating configuration: project settings from `pyproject.toml` under the package's own table, release notes from `.github/release.yml`. Infer what can be inferred, such as the package name from `[project].name`. Bundle data files inside the package and read them with `importlib.resources`.

Version bumps belong to a release, never to a change: bump immediately after releasing, so the tree always carries the next release's version. A downstream pin is different. It is part of the change that creates the dependency, so when a change makes one package consume another's new behaviour, stamp the consumer's pin in the same session. A pin deferred to release time is a forgotten pin.

## Ramabana workflow

Use Ramabana's native tools rather than instructions written for another harness:

- `search_code` finds repository and installed-package behaviour.
- `view_file` or the notebook cell tools read the exact source before editing.
- `replace_text`, `edit_file` or `edit_cell` make narrow, auditable changes.
- `inspect_python` reads live state without mutation; `run_python` performs requested transformations in new bindings.
- `run_shell` verifies edits with the repository's own commands.
- `read_skill` loads specialized workflows before using them. For the prose that ships with code, read `write_docs`; for narrative writing, `write_prose`; for the design a codebase is derived from, `theory`.

A task is not complete because code was written. Run the relevant tests or checks, read the result, fix failures, and report exactly what was verified. Never claim a file changed or a check passed without tool evidence from the current session.

Docs: https://vedicreader.github.io/ramabana/coding_patterns.html.md"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/09_coding_patterns.ipynb.

# %% auto #0
__all__ = []

# %% ../nbs/09_coding_patterns.ipynb #7eb8eb26
__all__ = []
