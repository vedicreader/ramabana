---
name: kosha
description: >
  Surface repo code and installed package snippets before writing new code.
  Run at the start of any task that touches existing patterns or packages.
  Skip when it's a small change and you know the exact file to look at.
---

# kosha — repo + package memory for coding agents

FTS5 + vector search + call graph over your repo and installed packages.
**Use before Grep, Read, or web search** whenever the question is about existing code or packages.

## When to use / skip

**Use when** you're about to `Read` a source file to learn an API, `grep` for a
function/pattern, check whether a dependency already does something, or decide where
new code goes. "I know where to look" is the skip trap — knowing the file ≠ knowing
what's already there.

**Skip when** the path is a known config/lockfile (not code), the task is pure file
structure, or you already have the relevant kosha results in context.

## Invoke

Start the daemon once per session to avoid the ~3–5s embedding cold-start on every call:

```bash
kosha daemon &
```

In-process (`uv run kosha` > `clikernel` if available > `.venv/bin/python`):

```python
from kosha import Kosha
k = Kosha()
k.status()   # always first → {files, packages, graph_nodes, stale_files, stale_pkgs}
k.sync(in_parallel=True)   # ONLY if files/pkgs you need are stale; stale looks like missing
```

**Quick scan (the minimum viable call)** — run before opening any file:

```python
for r in k.env_context('description of what you want', limit=10):
    print(r['metadata']['mod_name'], r['metadata'].get('lineno',''), r['content'][:120])
```

## Methods

| Question | Call |
|----------|------|
| Is the index fresh? | `k.status()` |
| Does this exist in a dependency? (package-only, faster) | `k.env_context('desc', limit=8)` |
| What pattern is used in the repo? (default; add repo results + graph) | `k.context('desc', graph=True, limit=15)` |
| Repo-only search | `k.repo_context('desc')` |
| Triage many results without full code bodies | `k.context('desc', compact=True)` |
| Who calls this / what does it call / registered peers? | `k.ni('pkg.mod.fn')` |
| How do two nodes connect? | `k.short_path('a.fn', 'b.fn')` |
| What's a package's real public API? (`__all__` + `@patch`) | `k.public_api('pkg')` |
| Where do I add new code? (returns `file:line` insertion points) | `k.where_to_add('desc', limit=5)` |
| Rebuild call graph without re-embedding (e.g. after kosha update) | `k.sync(embed=False)` |

`context(q, graph=True)` is the right default once a task touches more than one module.
`env_context` is already a semantic similarity search — pass any description, snippet, or
function name; no separate `similar()` needed.

## Filter syntax

Filters combine with natural language in one query string; bare package names auto-detect as `package:`.

| Token | Example | Effect |
|-------|---------|--------|
| `package:name` | `package:fastcore` | Restrict to one package |
| `path:pattern` | `path:xtras` | Restrict by path substring |
| `file:glob` | `file:xtras*` | Restrict by filename glob |
| `lang:ext` | `lang:py` | Filter by language |
| `type:node` | `type:FunctionDef` | Filter by AST node type |

## Reading a result

```python
{'content': 'def merge(...): ...',
 'metadata': {'mod_name': 'fastcore.basics.merge',  # use for ni()/short_path()
              'path': '...', 'lineno': 655, 'type': 'FunctionDef', 'package': 'fastcore'},
 'pagerank': 0.00027,          # centrality = blast radius; high → load-bearing, touch carefully
 'callers': [...], 'callees': [...],
 'co_dispatched': [...]}
```

**`co_dispatched`** — functions assigned together at module level (route groups, handler
tables, plugin registries). When adding a new handler, this shows the peers to pattern-match
and where the registration lives, without reading the glue code.

## Pointers

- **MCP server:** if `kosha-mcp` is configured in the host (`claude mcp add kosha -- uv run kosha-mcp`),
  the same operations are available as MCP tools (`status`, `context`, `env_context`, `node_info`,
  `where_to_add`, ...) — call those directly instead of the in-process API.
- **Daemon protocol:** send JSON `{"cmd": "...", "args": {...}}` on stdin. Commands: `sync`,
  `context`, `repo_context`, `env_context`, `ni`, `top_nodes`, `public_api`, `api_call_paths`,
  `status`, `where_to_add`.
- **Package docs:** `from kosha.core import pkg_url` → repo/docs URL; feed to WebFetch (or
  fossick if installed) for usage examples, or WebSearch for changelogs. nbdev docs anchor on
  the function name (`#fn`); GitHub → `read_gh_file`.
- **`k.codedb` / `k.envdb` are `litesearch.Database` objects** — full litesearch API (custom
  stores, raw SQL) works directly. See the `/litesearch` skill.
