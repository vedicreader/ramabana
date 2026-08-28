# Splitting the toolset out of Ramabana

> **For agentic workers:** this plan spans four repositories and one that does not exist yet. Read "State on 2026-08-28" before starting: it records measurements taken from the working trees on that date, and a later session must re-measure rather than trust them. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ramabana keeps the agent. A new package, `yantras`, owns the host protocols, the tool factories and the skills registry. Leela and any other frontend then take the tools without taking the agent loop.

**Architecture after the split:** `uraiyadal` holds the chat conventions, the runtime registry, `ModelSpec` and `resolve`. `rishi` holds the local and hosted engines and registers them with `uraiyadal`. `gheasy` holds the git and GitHub plumbing. `yantras` holds the host protocols, the capability mixins, the tool factories, the skills registry and the tool-result conventions. `ramabana` holds the agent loop, context compaction, sessions and branches, approvals, routing and budgets, subagent delegation, and the CLI, MCP and ACP frontends. `leela` is the application.

**Package name:** `yantras`. PyPI returned 404 for it on 2026-08-28. `yantra`, singular, is taken by an unrelated plugin framework at 0.7.1. Re-check availability before the first upload.

## State on 2026-08-28

Two of the four extractions are done, and one went further than planned.

`uraiyadal` 0.0.4 is published. `rishi` 0.1.32 depends on it. `rishi/core.py` is 106 lines, down from 1715. `uraiyadal` 0.0.4 exports `ModelSpec`, `resolve`, `Runtime`, `RUNTIMES`, `register_runtime`, `hosted_ctx`, `cfg_caps`, `mmproj_caps`, `hosted_caps`, `fallback_caps` and `tbl_caps`.

`ramabana/core.py` line 307 declares its own frozen `ModelSpec` with the same fields as urai's under different names: `backend` for `runtime`, `config` for `opts`. Line 358 declares its own `resolve`, 35 lines of per-runtime branching that urai's `RUNTIMES` registry now does generically. This duplication is Task 1.

`gheasy` 0.0.9 exports 25 of the 26 names `ramabana/git.py` exports. The one it does not carry is `git_tools`, the tool-factory wrapper. `_invalidate`, `_plural` and `_unborn` exist in `gheasy/repo.py` and are absent from its `__all__`. Leela imports all three from `ramabana.git` today.

## Why the toolset cannot be extracted first

The measurements below come from `ramabana` at `1752135`.

`Host` in `ramabana/tools.py` declares 44 methods across eleven tool groups. `NullHost` overrides 32 of them, `LocalHost` all 44, and Leela's `WorkspaceHost` about 50. Twenty of `NullHost`'s overrides have bodies that restate the base class contract.

Capability detection uses three mechanisms at once. `capabilities` is a declared dict. `_supports` asks whether the subclass overrode the method. `_probe` calls the method and catches `NotImplementedError`. `_takes_reading` inspects the signature of `check` for backward compatibility. `tools_for` is thirty lines of per-group special cases naming which mechanism applies where.

`api_tools` calls `host.api_load`, `host.api_ops`, `host.api_count` and `host.api_call`. `Host` declares none of them. The api group is held together by `SpecHost` announcing itself in the `capabilities` dict.

Nine host classes exist in `ramabana`. Four of them add exactly one capability group to `LocalHost`: `SpecHost` adds api, `VaultHost` adds memory, watches and web, `DhrishtiHost` adds the kernel session, `shop.py` adds the cart. They compose by inheritance, so a host can have one. `mk_host` in `cli.py` line 1902 works around this by synthesising a class at runtime:

```python
Host = LocalHost if not bases else bases[0] if len(bases) == 1 else type('VaultSpecHost', tuple(bases), {})
```

`FullHost` in `testing.py` is the same union assembled by hand.

### The defect this causes

`enter_python` in `cli.py` replaces the agent's host with a fresh `DhrishtiHost` built from four attributes of the old one. `use_host` assigns `agent.host` and calls `refresh()`, so `tools_for` recomputes against a host that is `LocalHost` plus a kernel. Measured on 2026-08-28:

```
mk_host(roots=('.',), vault=True, spec=True) -> VaultSpecHost
lost on /python: ['api_call', 'api_load', 'api_ops', 'ask_memory', 'cancel_watch',
                  'list_watches', 'memory_forget', 'memory_read', 'memory_search',
                  'memory_topics', 'memory_tree', 'poll_watches', 'remember',
                  'set_reminder', 'watch_url']
gained: []
```

`ramabana --vault --spec` followed by `/python` drops fifteen tools and gains none. `LocalHost` already answers `run_python`, `inspect_python` and `list_vars`, so the session group was present before the swap. `DhrishtiHost` upgrades those three to a real kernel and adds no tool. `attach_session` builds the host the same way and loses the same fifteen. Task 2 fixes this.

### Why the extraction is nonetheless small

`tools.py` imports `Run`, `current_run` and `run_context` from `runtime`. All three are used only inside `delegate` and `delegate_many`. `tools.py` imports `AgentError`, `agent_err` and `spec_caps` from `core`, and `spec_caps` is used once, at line 1580. `tools.py` never reads `host.approvals`. Take the subagent code out and the toolset's tie to the rest of Ramabana is five error-handling names.

`tools.py` and `git.py` import each other. `tools_for` imports `git_tools` inside the function body; `git.py` imports `GIT_READ_TOOLS`, `GIT_WRITE_TOOLS`, `GIT_TOOLS`, `MAX_TOOL_CHARS`, `clip` and `err` at module level. Task 5 removes the cycle.

## Global constraints

- **This is an nbdev project. Edit `nbs/*.ipynb`, never `ramabana/*.py`.** Every module is generated and carries `# AUTOGENERATED! DO NOT EDIT!`. Run `nbdev-prepare` (hyphen) before every commit.
- **Never parse an `.ipynb` as JSON.** Use `NotebookEdit`, or `fastcore.nbio` (`read_nb`, `write_nb`, `mk_cell`) in code, per `.agents/skills/nbio-notebook-edits/SKILL.md`.
- **Packaging changes go in `pyproject.toml` under `[tool.hatch.build]`.** This checkout is hatchling. Do not use `MANIFEST.in`.
- **Installs go through `uv add`.** Never `pip install`. Version bumps belong to a release, never to a change.
- `cd` and shell `for` loops are blocked by the safecmd allowlist. Use absolute paths.
- **Every behaviour change gets a focused regression test.** Write the readable case as an executable cell in the source notebook. Assert the contract in bulk in `tests/`, hand-written pytest with sentence-style names and doubles from `ramabana.testing`. No test loads a model.
- **Ramabana keeps re-exporting every moved name** until Leela has migrated. `leela/agent/tools.py` is one line, `sys.modules[__name__] = ramabana.tools`, and it must keep resolving through Tasks 3 to 5.

## Tasks

### Task 1: Collapse `ramabana.core` onto uraiyadal

Independent of every other task. Do it first, because it shrinks what Task 2 has to reason about.

**Files:** `nbs/00_core.ipynb`, `pyproject.toml`, `tests/test_routing.py`

- [ ] Add `uraiyadal` to `dependencies` in `pyproject.toml` with `uv add`.
- [ ] Delete `ramabana`'s `ModelSpec` and re-export urai's. Urai names the fields `runtime` and `opts` where Ramabana names them `backend` and `config`. Ramabana's `ModelSpec.runtime` is already a property returning `backend`, so the read path survives; find every write of `backend=` and `config=`.
- [ ] Delete `ramabana`'s `resolve`. Register Ramabana's runtimes through `register_runtime` and call urai's `resolve`.
- [ ] Keep the `MODELS` short-name catalogue, `CUSTOM`, `register_model`, `unregister_model`, the `RETIRED` prefixes, `runtime_available`, `runtime_remedy` and `auth_status`. These are Ramabana's, not urai's.
- [ ] Resolve the `RUNTIMES` collision. `ramabana.core.RUNTIMES` is a tuple of seven runtime names. `urai.RUNTIMES` is a dict registry. Leela calls `tuple(RUNTIMES)` in `leela/blocks/agent/models.py`, which returns the keys either way, so the collision will not raise. Decide which one Ramabana exports and say so in the changelog.
- [ ] Delete `_caps` and its "None where rishi predates it" shim. The floor is now a `uraiyadal` version.
- [ ] Repoint the ten `from rishi.core import ...` sites at `urai`: `split_think`, `resp_text`, `tag_call_shape`, `StreamFormatter`, `ChatCallback` and `Chat` in `runtime.py` and `agent.py`, `infer_runtime`, `model_caps` and `resolve_runtime` in `core.py`, `CachedChat` in `testing.py`. Leave `rishi.claude`, `rishi.copilot`, `rishi.ollama`, `rishi.mlx` and `rishi.llama` alone.
- [ ] Replace `runtime.estimate_tokens` with `urai.msgs.est_tokens` plus the tokenizer hook, or keep the hook and call urai underneath.

**Acceptance:** `uv run pytest tests/test_routing.py` passes unchanged. Resolving a short name, a `runtime/model` prefix, a full repo id and a local path each return the same `ModelSpec` field values as before.

**Leela sees this task.** It imports `resolve`, `RUNTIMES`, `AGENTS`, `MODELS`, `CUSTOM`, `DFLT_LOCAL`, `spec_caps`, `estimate_tokens`, `model_note`, `available_models`, `auth_status`, `runtime_available`, `runtime_remedy`, `register_model` and `unregister_model` from `ramabana.core`. Every one of them must keep resolving from `ramabana` after this task, whatever they now wrap.

### Task 2: Capability groups become mixins

**Files:** `nbs/02_tools.ipynb`, `nbs/05_cli.ipynb`, `nbs/10_spec.ipynb`, `nbs/07_vault.ipynb`, `nbs/11_pyrepl.ipynb`, `nbs/08_shop.ipynb`, `nbs/04_testing.ipynb`, `tests/test_tools.py`

- [ ] Reduce `Host` to the path boundary every group needs: `roots`, `added_roots`, `add_root`, `check`, `walk`, `read`, `write`, `text_at`, `note`.
- [ ] Declare one protocol per group: code search, web, memory, watches, notebooks, session, shell, api. Give api the declaration it has never had: `api_load`, `api_ops`, `api_count`, `api_call`.
- [ ] Keep a class named `Host` that inherits every protocol. Existing subclasses, Leela's `WorkspaceHost` and all test doubles included, must keep working untouched. New hosts mix in only what they have.
- [ ] Turn `SpecHost`, `VaultHost`, `DhrishtiHost` and the shop group into mixins over the small `Host` rather than subclasses of `LocalHost`.
- [ ] Rewrite `tools_for` as a loop over `(protocol, factory)` pairs with `isinstance` as the test.
- [ ] Delete `capabilities`, `_declared`, `_probe`, `_supports`, `_has` and `_takes_reading`. Fold `readable` into `check`.
- [ ] Change `mk_host` to mix in the requested groups. Remove the `type()` call.
- [ ] Change `enter_python` and `attach_session` to mix the kernel group into the host they already have. Neither may construct a replacement host.
- [ ] Decide whether `approvals` stays declared on the yantras-side `Host`. `tools.py` never reads it. Recording the decision matters more than which way it goes.

**Acceptance:** a regression test asserts that the tool-name set after entering python mode is a superset of the set before it, for a host built with `vault=True, spec=True`. The fifteen tools listed above must survive. `uv run pytest` and `uv run nbdev-test` both pass.

### Task 3: Split `tools.py` inside Ramabana

Do this before extracting anything. The protocols from Task 2 are what tell you where to cut.

**Files:** new notebooks under `nbs/`, `nbs/02_tools.ipynb`

- [ ] Cut `tools.py` (2241 lines) into four: the tool-result conventions (`Hit`, `clip`, `clip_lines`, `err`, `failed`, `ERR`, `MAX_TOOL_CHARS`, `MAX_HITS`, `MAX_GREP_HITS`, `_cmds`, `_edits`, `_apply_edits`, `_diff`), the host protocols and the reference hosts, the tool factories, and the skills registry (`Skill`, `discover`, `skill_index`, `find`, `Registry`, `load`, `skill_dirs`, `ext_dirs`).
- [ ] Move `delegate`, `delegate_many` and `subagent_tools` out of the toolset and next to the agent. They are the only part needing a `Backend` and a `Run`. `monitor.py` imports `delegate` and moves with them.
- [ ] Keep `ramabana/tools.py` as a module that re-exports every name, so `sys.modules[__name__] = ramabana.tools` in Leela keeps resolving.
- [ ] Replace the hardcoded `WRITE_TOOLS` frozenset with a per-tool declaration. It currently names tools defined in `git.py` and `shop.py` from inside `tools.py`.

**Acceptance:** `uv run pytest` passes with no test file edited. Importing every name Leela uses from `ramabana.tools` still works.

### Task 4: Cut `yantras`

- [ ] Create the repository and the nbdev scaffold. Copy the four notebooks from Task 3.
- [ ] Make each capability group an optional extra: `[code]` pulls `koshas` and `litesearch`, `[web]` pulls `fossick`, `[memory]` pulls `vishalakshi`, `[api]` pulls `fastspec`, `[git]` pulls `gheasy`. The base install pulls `fastcore` only.
- [ ] Add `yantras` to Ramabana's dependencies. Reduce Ramabana's four modules to re-exports.
- [ ] Move `MemHost` and `FullHost` from `ramabana/testing.py` to `yantras`. The agent doubles stay in Ramabana.

**Acceptance:** `yantras` installs with no extras and its own test suite passes. Ramabana's suite passes against the published `yantras`.

### Task 5: Point `git_tools` at gheasy

- [ ] Promote `_invalidate`, `_plural` and `_unborn` to gheasy's `__all__`. Leela already imports all three.
- [ ] Rewrite `git_tools` in `yantras` against `gheasy`. Move `GIT_READ_TOOLS`, `GIT_WRITE_TOOLS` and `GIT_TOOLS` to `yantras`, since they are tool names.
- [ ] Delete `ramabana/git.py` and `nbs/12_git.ipynb`. Re-export from `gheasy` for one release.

**Acceptance:** `uv run pytest tests/test_git.py` passes against `gheasy`. No import cycle remains.

### Task 6: Publish the pyskills

`coding_patterns`, `theory`, `write_prose` and `write_docs` are 317 lines with no imports and no importers, already published through `[project.entry-points.pyskills]`.

- [ ] Decide whether they ship from `yantras` or their own package. Anything that wants `write_docs` today installs Ramabana and its whole dependency tree.
- [ ] Keep the `Skill.text` clipping contract wherever the loader ends up. `tests/test_skills.py` pins it, and `write_prose` sits just under `MAX_SKILL_CHARS`.

### Task 7: Leela adopts yantras

Leela's own session, after Task 5. Leela imports 64 names from Ramabana today, measured on 2026-08-28. The split sends them four ways.

| goes to | names |
|---|---|
| `yantras` | `Host`, `SpecHost`, `MAX_OPS`, `tools_for`, `clip`, `err`, `failed`, `save_media`, `DENY`, `MAX_HITS`, `MAX_TOOL_CHARS`, `MAX_GREP_HITS`, `WRITE_TOOLS`, `GIT_TOOLS`, `GIT_READ_TOOLS`, `GIT_WRITE_TOOLS`, and the privates `_cmds`, `_edits`, `_apply_edits` |
| `gheasy` | `GitError`, `GitRepo`, `clone`, `clone_target`, `gateway`, `repo_root`, `url_name`, and the privates `_invalidate`, `_plural`, `_unborn` |
| `uraiyadal`, reachable through Ramabana | `resolve`, `RUNTIMES`, `spec_caps`, `estimate_tokens` |
| `ramabana` | `Agent`, `Approvals`, `Ask`, `Backend`, `Completer`, `Routing`, `AgentError`, `agent_err`, `env`, `answer_md`, `ask_md`, `preview_for`, `_summary`, `Attachment`, `MEDIA`, `media_note`, `media_parts`, `safe_shelf`, `AGENTS`, `MODELS`, `CUSTOM`, `JOBS`, `DFLT_LOCAL`, `auth_status`, `available_models`, `model_note`, `register_model`, `unregister_model`, `runtime_available`, `runtime_remedy`, `ACTION_NOTICE`, `prompt_notices` |

- [ ] Promote the six private names that cross a new package boundary: `_cmds`, `_edits` and `_apply_edits` into `yantras`, `_invalidate`, `_plural` and `_unborn` into `gheasy`. A private imported across a package boundary is a public name that has not been renamed. `_summary` stays inside Ramabana and can be promoted separately.
- [ ] Repoint `leela/agent/tools.py` at `yantras`.
- [ ] Rebuild `WorkspaceHost` on the mixins. It reimplements memory, api, session, shell, notebook and web from scratch today because it cannot inherit from `LocalHost`.

## Decision: do not fetch the pyskills over the network

Rejected on 2026-08-28. Fetching the four skill bodies from `AnswerDotAI/aai-coding` with `fossick` on first load, and caching them, would not refresh them. It would replace them.

Diffed against `https://raw.githubusercontent.com/AnswerDotAI/aai-coding/main/aai_coding/`:

| skill | upstream lines | ramabana lines | lines differing |
|---|---|---|---|
| `coding_patterns` | 135 | 97 | 150 of 232 |
| `write_prose` | 127 | 94 | 141 of 221 |
| `write_docs` | 101 | 92 | 123 of 193 |
| `theory` | 23 | 34 | 37 of 57 |

They are rewrites, which is what `CLAUDE.md` says they are. Upstream's `theory.py` opens with `r'''`, and `CLAUDE.md` forbids the `r` prefix in a Ramabana skill body.

Three further reasons. `INLINE_SKILLS = ('exhash', 'coding_patterns')` puts `coding_patterns` in every briefing, so a fetch on first load makes the system prompt depend on GitHub being reachable, in a stack built for local models. `Skill.text` clips at `MAX_SKILL_CHARS`, so an upstream edit would truncate a body mid-sentence with no test able to catch it. An agent whose briefing changes when someone pushes to another repository is not reproducible.

Fetch-on-demand is still worth building for skills that are not inlined, with the packaged copy as the fallback and never as the only source. It is not worth building for these four.

## Open questions

- Where the four pyskills ship from. Task 6 records the choice.
- Whether `approvals` stays on the yantras-side `Host` protocol. Task 2 records the choice.
- How long Ramabana re-exports the moved names. One release is enough if Leela migrates in the same window.
- Whether `Compactor`, `surgical_history` and `summarise_prompt` in `runtime.py` should move down into `uraiyadal` alongside `evict_middle` and `SlidingWindowCallback`. Urai's are mechanical eviction and Ramabana's summarise through a model, so they are related and not duplicates. Not part of this plan.
