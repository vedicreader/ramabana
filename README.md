# ramabana

> ramabana (रामबाण) — an agentic harness for on-device models: skills via pyskills + SKILL.md, a skill finder, fenced python execution, and controlled conversation compaction over [rishi](https://github.com/vedicreader/rishi)/litert_lm.

ramabana turns a local [rishi](https://github.com/vedicreader/rishi) `Chat` into an agent. It
discovers skills from two sources — [pyskills](https://answerdotai.github.io/pyskills/) entry points
(e.g. [kosha](https://github.com/vedicreader/kosha) and
[fossick](https://github.com/vedicreader/fossick)) and Claude-Code-style `SKILL.md` directories —
picks the right ones for each request, and runs the model in a code-execution loop with an approval
gate and schema-enforced conversation compaction.

## Install

``` sh
pip install ramabana
```

## Quickstart

``` python
from ramabana import Harness

h = Harness(retain=['Open task list', 'Files touched so far'])
h('Find what fetch() returns in fossick and summarize it.')
```

`Harness()` builds a rishi `Chat` lazily on first use. Each call:

1. **finds skills** — `Finder` ranks every registered skill (pyskills entry points + `SKILL.md`
   dirs) against the request; lexical by default, or pass `embed=` for embedding search.
2. **loads them** — SKILL.md bodies go in as `<skill>` blocks; pyskills are star-imported into the
   executor namespace and documented via `doc()`.
3. **runs the loop** — the model replies with ```` ```python ```` fences; the executor runs them
   in a persistent Jupyter kernel (approval-gated, interruptible, restartable) and feeds output back
   as ```` ```result ```` fences until the model answers in prose.
4. **compacts when needed** — past `compact_at` context fullness, the conversation is summarized
   through a *retain-list schema* (`chat.structured`, so every retained item is a required field)
   and a fresh chat on the same engine takes over. The executor namespace survives compaction.

## The pieces

| Module | What it does |
|---|---|
| `registry` | One `Skill` list over pyskills entry points and `SKILL.md` dirs; `catalog()`, `load()` |
| `finder` | Rank skills against a request (lexical or `embed=`); optional `chat.classify` confirm |
| `executor` | Persistent Jupyter kernel per session ([conkernelclient](https://github.com/AnswerDotAI/conkernelclient)) with a rishi-compatible `approve` gate; interrupt/restart/timeout; in-process fallback |
| `compact` | `compact(chat, retain=[...])` — structured summary, fresh chat on the same engine |
| `harness` | `Harness` — the loop tying it all together |

## Giving it skills

Any package that registers a `pyskills` entry point is discovered automatically — kosha (repo +
package search) and fossick (web search/fetch/browse) both ship one. Project-local prose skills go
in `.claude/skills/<name>/SKILL.md` with the usual frontmatter (`name`, `description`, optional
`triggers`).

## Working on ramabana

It's an nbdev project: edit the notebooks in `nbs/`, not the generated modules in `ramabana/`.
Run `nbdev-prepare` after changes.
