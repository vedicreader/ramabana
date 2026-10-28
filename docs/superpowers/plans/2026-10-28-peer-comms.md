# Peer talk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code, Codex and Ramabana sessions on one Mac find each other and exchange notes, asks and replies, with work together mode, a folder guard and a morning report.

**Architecture:** A light module `ramabana/peers.py` owns everything on disk under one peers folder: the log, per-session inbox files, registrations of non-Ramabana sessions, work together state and limits. A message is always posted to the receiver's inbox file; for a Ramabana receiver the control socket is only a doorbell (`message` method). Claude Code and Codex reach it through hooks that call `ramabana peer-hook <kind> <event>`, installed by `ramabana setup peers`.

**Tech Stack:** Python 3.12, nbdev (notebooks in `nbs/` are the source), fastcore, hatchling, pytest, Claude Code hooks, Codex hooks.

**Spec:** `docs/superpowers/specs/2026-10-28-peer-comms-design.md`

**Order:** 1, 2, 3, 7, 4, 5, 6, 8, 9. Task 4 and Task 6 call `save_report` from Task 7, which needs only Tasks 1–2.

## Global Constraints
- Edit notebooks only; then `uv run nbdev-export`. Never hand-edit `ramabana/*.py`, `README.md`, `_modidx.py` or `nbs/llms.txt`. Use `NotebookEdit` or `fastcore.nbio`, never JSON edits.
- Read the `coding_patterns` skill (`nbs/09_coding_patterns.ipynb`) first. fastcore idioms, functional style, one-line docstrings, no comments that restate code.
- Every notebook follows the reading format: a short intro, short sections, a lead sentence per cell, small explained test cells.
- All prose (docs, UI text, hook text, report) is ASD-STE100, grade 9.
- `ramabana/peers.py` and `ramabana/peer_hooks.py` must not import `ramabana.agent`, `ramabana.control` or `ramabana.cli` at module level: sync hooks must stay fast (no network, no model calls).
- Tests use a temporary peers folder (`$RAMABANA_PEERS`) and a temporary `cfg` under `/tmp` (socket paths stay short). Never the real `~/.config/ramabana` or `~/.claude`, no tmux, no browser, no window focus.
- Values: `HOP_MAX = 6`; `PEER_BUDGET = {'messages': 40, 'turns': 20}`; `TOGETHER_HOURS = 12`.
- Commits: one terse line, no co-author line.

## Review Focus
- Two consumers of one inbox (a hook and `tell --wait`, or the doorbell and the `tell` tool) must never both take the same message: taking is by id under a lock. Test: `test_take_is_once_under_threads` (Task 1).
- A Claude session that `/clear`s gets a new session id: the old registration must not linger as a live peer with the same pid. Test: `test_reregister_same_pid_replaces_old` (Task 2).
- `--until 07:00` given at 23:00 means tomorrow 07:00, and given at 06:00 means today. Test: `test_until_rolls_to_next_day` (Task 2).
- The async waiter must not pile up across Stop events, and must exit when the session ends. Test: `test_second_waiter_exits_at_once` and `test_waiter_exits_on_unregister` (Task 6).
- A path given as relative or through a symlink must still hit the folder guard. Test: `test_guard_resolves_paths` (Task 2).

---

### Task 1: The peers folder, the envelope, the log and inboxes

**Files:**
- Create: `nbs/23_peers.ipynb` → `ramabana/peers.py`
- Modify: `nbs/20_control.ipynb` (move `control_call` out; import it from `peers`)
- Test: notebook cells, and `tests/test_peer_store.py`

**Interfaces:**
- Produces:
  - `peers_dir(cfg=None) -> Path`: `$RAMABANA_PEERS`, else `Path(cfg or '~/.config/ramabana').expanduser()/'peers'`; created on first use.
  - `@dataclass Envelope(kind: str, text: str, frm: dict, to: str = '', repo: str = '', thread: str = '', hops: int = 0, changes: list = [], proof: list = [], id: str = '', at: float = 0.)`. `kind` is `note|ask|reply`. `id` defaults to `uuid4().hex[:12]`, `thread` to `id`, `at` to `time.time()`. `.dict()` writes `frm` as `'from'`; `Envelope.load(d)` reads it back.
  - `log(d, row: dict)`, `read_log(d, since=0.) -> list[dict]` on `d/'log.jsonl'`. Rows are envelope dicts, or event rows `{'event': ..., 'at': ..., **kw}`.
  - `post(d, key: str, env: Envelope)`: append to `d/f'{key}.inbox.jsonl'` and to the log.
  - `take(d, key, pred=None) -> list[Envelope]`: the inbox rows not yet taken that match `pred`, marked taken by id in `d/f'{key}.taken'`, under an `fcntl` lock on that file.
  - `wait_take(d, key, timeout, pred=None, alive=lambda: True, poll=.5) -> list[Envelope]`: `take` until something comes, `timeout` passes (None waits forever) or `alive()` is false.
  - `control_call(path, method, timeout=30, **params)`: moved unchanged from `control.py`; `control.py` re-exports it.
  - A peer key is `f'{kind}-{session}'`.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_store.py`:

```python
def test_envelope_round_trip(tmp_path):
    e = Envelope('ask', 'build Card', {'kind': 'claude', 'session': 's1', 'name': 'abhyasa'}, to='leela', repo='rupaka')
    assert e.thread == e.id and len(e.id) == 12
    assert Envelope.load(e.dict()) == e and e.dict()['from']['name'] == 'abhyasa'

def test_post_logs_and_take_is_once(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    d = peers_dir()
    post(d, 'claude-s2', Envelope('note', 'new shortcut', {'session': 's1'}))
    assert [e.text for e in take(d, 'claude-s2')] == ['new shortcut']
    assert take(d, 'claude-s2') == [] and len(read_log(d)) == 1

def test_take_filters_by_pred(tmp_path):
    post(tmp_path, 'k', a := Envelope('reply', 'r1', {}, thread='t1'))
    post(tmp_path, 'k', Envelope('note', 'n', {}))
    assert take(tmp_path, 'k', lambda e: e.thread == 't1') == [a]
    assert [e.text for e in take(tmp_path, 'k')] == ['n']

def test_take_is_once_under_threads(tmp_path):
    for i in range(50): post(tmp_path, 'k', Envelope('note', str(i), {}))
    with ThreadPoolExecutor(8) as ex: got = [e.id for r in ex.map(lambda _: take(tmp_path, 'k'), range(8)) for e in r]
    assert len(got) == 50 == len(set(got))

def test_wait_take_returns_when_posted(tmp_path):
    threading.Timer(.3, post, (tmp_path, 'k', Envelope('note', 'hi', {}))).start()
    assert [e.text for e in wait_take(tmp_path, 'k', 5, poll=.05)] == ['hi']
    assert wait_take(tmp_path, 'k', .2, poll=.05) == []
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `uv run pytest tests/test_peer_store.py -q`. Expected: FAIL, `ModuleNotFoundError: ramabana.peers`.
- [ ] **Step 3: Write `nbs/23_peers.ipynb`** (`#| default_exp peers`) with the intro, then the cells for the names above, each with one small explained test cell. Move `control_call` from `nbs/20_control.ipynb`; there, `from .peers import control_call`.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_store.py tests/test_control.py tests/test_peers.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `git add nbs/23_peers.ipynb nbs/20_control.ipynb ramabana tests/test_peer_store.py && git commit -m "Add the peers store: envelope, log and inboxes"`

### Task 2: Registration, work together state, limits, targets and the folder guard

**Files:**
- Modify: `nbs/23_peers.ipynb`
- Test: `tests/test_peer_rules.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `register(d, kind, session, folders, pid, name='') -> dict`: writes `d/f'{kind}-{session}.json'` as `{kind, session, name, folders, pid, key, at}`. `name` defaults to `f'{Path(folders[0]).name} · {kind}'`. Removes any other registration of the same `kind` and `pid` (a `/clear` gives a new id).
  - `unregister(d, kind, session)`; `registered(d) -> list[dict]`: live rows only; a row whose `pid` is dead is removed.
  - `add_folder(d, key, path) -> dict`.
  - `pid_alive(pid) -> bool`; `agent_pid(names=('claude', 'codex')) -> int`: the nearest ancestor whose command base name is in `names` (via `ps -o ppid=,comm= -p`), else `os.getppid()`.
  - `git_root(path) -> str`: `git rev-parse --show-toplevel`, else the resolved `path`.
  - `HOP_MAX`, `PEER_BUDGET`, `TOGETHER_HOURS` (Global Constraints values).
  - `together_on(d, key, partners=(), until=None, now=None) -> dict`: writes `d/f'{key}.together.json'` as `{started, until, partners}`. `until` is `'HH:MM'` (the next such local time after `now`) or None (`now + TOGETHER_HOURS` h).
  - `together_off(d, key) -> dict|None`: removes it; returns the state that ended.
  - `together_state(d, key, now=None) -> dict|None`: None when off; when expired, ends it, writes the event row `{'event': 'together_end', 'key', 'started'}` and returns None.
  - `is_partner(state, frm: dict) -> bool`: no `partners` means all; else a partner matches `frm['name']`, its first word, or a folder base name.
  - `limit_refusal(d, key, env, now=None) -> str`: '' or why: `env.hops >= HOP_MAX`, or, in work together mode, messages from `key` since `started` ≥ `PEER_BUDGET['messages']`, or asks to `key` since `started` ≥ `PEER_BUDGET['turns']`. A refusal writes `{'event': 'refused', 'key', 'why', 'thread'}`.
  - `match_peer(rows, target) -> dict`: by list number (from 1), session id, `key`, or folder base name. No match raises `LookupError('no live session ...')`; more than one raises `LookupError` that lists the matches with their numbers.
  - `folder_denial(path, me: str, rows) -> str|None`: resolve `path` (relative to `Path.cwd()`, symlinks followed); refuse when a row other than `me` holds a folder containing it and `me`'s row does not.
  - `split_proof(text) -> tuple[str, list, list]`: lines starting `changes:` / `proof:` (case-insensitive) come out as list items split on `;`; the rest is the body.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_rules.py`:

```python
def test_registered_drops_dead_pid(tmp_path):
    register(tmp_path, 'claude', 's1', ['/r/abhyasa'], os.getpid())
    register(tmp_path, 'claude', 's2', ['/r/leela'], 999999)
    assert [r['key'] for r in registered(tmp_path)] == ['claude-s1']
    assert not (tmp_path/'claude-s2.json').exists()

def test_reregister_same_pid_replaces_old(tmp_path):
    register(tmp_path, 'claude', 'old', ['/r/a'], os.getpid())
    register(tmp_path, 'claude', 'new', ['/r/a'], os.getpid())
    assert [r['session'] for r in registered(tmp_path)] == ['new']

def test_until_rolls_to_next_day(tmp_path):
    late, early = datetime(2026, 10, 28, 23).timestamp(), datetime(2026, 10, 28, 6).timestamp()
    assert together_on(tmp_path, 'k', until='07:00', now=late)['until'] == datetime(2026, 10, 29, 7).timestamp()
    assert together_on(tmp_path, 'k', until='07:00', now=early)['until'] == datetime(2026, 10, 28, 7).timestamp()
    assert together_on(tmp_path, 'k', now=late)['until'] == late + 12*3600

def test_expired_together_ends_and_logs(tmp_path):
    together_on(tmp_path, 'k', now=0)
    assert together_state(tmp_path, 'k', now=13*3600) is None
    assert read_log(tmp_path)[-1]['event'] == 'together_end'

def test_hop_and_budget_refusals(tmp_path):
    assert 'hop' in limit_refusal(tmp_path, 'k', Envelope('reply', 'x', {}, hops=6))
    together_on(tmp_path, 'k')
    for i in range(40): log(tmp_path, Envelope('note', str(i), {'key': 'k'}).dict())
    assert 'budget' in limit_refusal(tmp_path, 'k', Envelope('note', 'x', {'key': 'k'}))

def test_match_peer_by_number_id_and_repo():
    rows = [{'session': 'a1', 'key': 'claude-a1', 'folders': ['/r/sanketa']}, {'session': 'b2', 'key': 'ramabana-b2', 'folders': ['/r/leela']}]
    assert match_peer(rows, '2')['session'] == 'b2' and match_peer(rows, 'sanketa')['session'] == 'a1'
    with pytest.raises(LookupError, match='1 .*sanketa'): match_peer(rows + [{**rows[0], 'session': 'c3', 'key': 'claude-c3'}], 'sanketa')

def test_guard_resolves_paths(tmp_path, monkeypatch):
    (own := tmp_path/'leela').mkdir(); (link := tmp_path/'l').symlink_to(own)
    rows = [{'key': 'ramabana-b2', 'folders': [str(own)]}, {'key': 'claude-a1', 'folders': [str(tmp_path/'abhyasa')]}]
    monkeypatch.chdir(tmp_path)
    assert folder_denial('leela/x.py', 'claude-a1', rows) and folder_denial(link/'x.py', 'claude-a1', rows)
    assert folder_denial('leela/x.py', 'ramabana-b2', rows) is None
    assert folder_denial('leela/x.py', 'claude-a1', rows + [{'key': 'claude-a1', 'folders': [str(own)]}]) is None

def test_split_proof():
    body, ch, pr = split_proof('Done.\nchanges: rupaka/card.py; abc123\nProof: uv run pytest -q → 12 passed')
    assert body == 'Done.' and ch == ['rupaka/card.py', 'abc123'] and pr == ['uv run pytest -q → 12 passed']
```

- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_rules.py -q`. Expected: FAIL with `ImportError`.
- [ ] **Step 3: Add the cells** for the names above to `nbs/23_peers.ipynb`, each with a lead sentence and a small test cell.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_store.py tests/test_peer_rules.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -am "Add peer registration, work together mode, limits and the folder guard"` (add the new test file first).

### Task 3: One peer list, `tell`, and the CLI subcommands

**Files:**
- Modify: `nbs/23_peers.ipynb`, `nbs/20_control.ipynb` (`peers_of`, `status`), `nbs/19_setup.ipynb` (`run_cli` dispatch)
- Test: `tests/test_peer_cli.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `socket_peers(cfg, timeout=2) -> list[dict]`: the body of today's `peers_of` without the self filter, each row plus `kind='ramabana'`, `key`, `path`.
  - `all_peers(cfg=None, exclude='') -> list[dict]`: `socket_peers` plus `registered(peers_dir(cfg))`, minus the row whose `key` or `session` is `exclude`, most recent first.
  - `control.peers_of(agent, timeout=PEER_WAIT)` becomes `all_peers(agent.cfg, exclude=agent.session_id)`. `Control.do_status` adds `'kind': 'ramabana'`, `'key'` and `'folders'` (all roots).
  - `me(cfg=None, session=None) -> dict`: the caller as `frm`: `--session` given, else `$CLAUDE_CODE_SESSION_ID` → the `claude-<id>` registration, else `{'kind': 'cli', 'session': 'cli', 'key': 'cli', 'name': 'cli'}`.
  - `tell(target, text, kind='note', frm=None, repo='', thread='', hops=0, everyone=False, wait=0, cfg=None) -> str`: resolve with `match_peer` (or every row for `everyone`, notes only), check `limit_refusal` for the sender, `post` to each receiver's inbox, ring a Ramabana receiver with `control_call(row['path'], 'message', id=env.id)`. With `wait`, `wait_take` on the sender's inbox for `kind == 'reply' and thread == env.thread`, and return its text plus `changes` and `proof`.
  - `peers_cli(argv) -> int` for `ramabana peers [--ids] [--add-folder PATH] [--session ID]`, `ramabana tell TARGET TEXT [--ask] [--reply-to THREAD] [--all] [--repo R] [--wait N] [--session ID]` (a reply's text goes through `split_proof`), `ramabana inbox [--wait N] [--session ID]`, `ramabana together on|off|status [--with A,B] [--until HH:MM] [--session ID]`. `together on` prints each partner's permission mode (Ramabana `status` gains `'approve'`, the gate's mode; registered agents show `unknown`).
  - `run_cli`: `if sys.argv[1:2] in (['peers'], ['tell'], ['inbox'], ['together']): return peers_cli(sys.argv[1:])`, before `need('cli')`.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_cli.py`: `test_all_peers_merges_sockets_and_registrations` (a live `Control` on a `fake_agent` in a `/tmp` cfg, plus one registration: both rows, `kind` set, self excluded); `test_tell_note_posts_and_rings` (the Ramabana receiver's inbox holds the note; the socket got `message` with its id); `test_tell_ask_waits_for_reply` (a thread posts a reply with the same `thread` after 0.2 s; `tell(..., wait=5)` returns its text); `test_tell_to_dead_session_fails_fast` (`LookupError`, nothing in the log); `test_tell_refused_over_hops` (returns the refusal, nothing posted); `test_me_reads_claude_env` (`CLAUDE_CODE_SESSION_ID=s1` with a registration → `frm['key'] == 'claude-s1'`); `test_cli_inbox_and_together` (`peers_cli(['inbox'])` prints and takes; `peers_cli(['together', 'on', '--until', '07:00'])` writes state; `off` removes it).
- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the names above. Keep `peers.py` free of agent imports; `control.py` imports from it.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_cli.py tests/test_peers.py tests/test_control.py tests/test_setup.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `"Add ramabana peers, tell, inbox and together commands"`

### Task 4: A Ramabana session receives messages

**Files:**
- Modify: `nbs/20_control.ipynb` (`Control`), `nbs/03_agent.ipynb` (`_prepare`, `_guard`), `nbs/05_cli.ipynb` (`UiControl`, `submit`, `start_control`, `/together`, `/tell`)
- Test: `tests/test_peer_receive.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `METHODS` gains `'message'`. `Control.do_message(id)`: `take` from `ramabana-<session>` and handle each envelope with `Control.receive(env)` on a daemon thread; returns `{'took': n}`.
  - `Control.receive(env)`:
    - `note` or `reply`: `agent.steer(peer_text(env))` when a turn runs, else `agent.peer_notes.append(env)`.
    - `ask` while `together_state` is on, `is_partner`, and `limit_refusal` is '': start or queue a turn on `peer_text(env)` (as `do_prompt`).
    - Any other `ask`: `agent.approvals.request('peer ask', {'from': name, 'repo': env.repo, 'text': env.text}, force=True, timeout=None)`. On yes, start the turn. On no, `tell` a reply `'refused: <note>'`. While waiting, the envelope is written to `d/f'{key}.pending.jsonl'` and removed after the answer.
  - `peer_text(env) -> str`: `<peer-message id=".." kind=".." from=".." repo="..">text</peer-message>`, plus for an ask a line telling the agent to read the `peer-work` skill and end with `changes:` / `proof:` lines.
  - Reply after a peer turn: `Control.start()` registers `before_turn` and `after_turn` on `agent.registry` (outside the extension span, so a reload keeps them). `before_turn` records the ask id found in a `peer-message kind="ask"` prompt. `after_turn(agent, text)` sends `tell(sender, body, kind='reply', thread=env.thread, hops=env.hops + 1)` with `changes` and `proof` from `split_proof(text)`.
  - `Agent.peer_notes: list` and `Agent.peer_notice() -> str`: drains the list into one `<peer-messages>` block. `_prepare` appends it next to `watch_notice()`.
  - `_guard`: when `writing`, also `folder_denial(path, f'ramabana-{self.session_id}', peers_of(self))`, using peers read at most once every 10 s (`self._peer_rows`, `self._peer_rows_at`).
  - `peer_tools(agent)`: `tell(session, text, kind='note', wait=60)` now calls `peers.tell` with `frm` = this session (`kind` is `note` or `ask`; `steer`/`prompt` are gone from the tool, but the socket methods stay). `peers()` lists all kinds with `kind` shown.
  - The control thread checks `together_state` once a minute; when a mode it saw on has ended, it runs `save_report` (Task 7) on a daemon thread.
  - In `nbs/05_cli.ipynb`: `UiControl.receive` goes through `self.ui._as_owner` the way `do_prompt` does. `submit` on a typed line ends work together mode (`together_off`) and, if it ended, shows the saved report (Task 7) or the hint `run ramabana report`. On startup and resume, `start_control` raises each pending ask again from `.pending.jsonl`. `/together on|off|status ...` uses `peers_cli` arguments; `/tell N --ask TEXT` sends an ask.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_receive.py`: `test_note_while_idle_joins_next_turn` (`do_message`; then `ask` on a `ScriptedBackend` agent shows `<peer-messages>` in the outgoing text); `test_note_while_running_steers`; `test_ask_needs_approval_by_default` (an `Approvals` gate with a listener sees `peer ask`; answering no posts a `refused` reply to the sender's inbox); `test_ask_in_together_mode_starts_turn_and_replies` (the sender's inbox gets a reply with `thread`, `hops == 1`, and `proof` parsed from the scripted reply); `test_ask_from_non_partner_still_asks`; `test_pending_ask_survives_restart` (a new `Control` on the same session raises it again); `test_guard_refuses_other_sessions_folder` (a registered Claude row holding a folder; `replace_text` there is refused with the folder named); `test_tell_tool_sends_ask_envelope`; `test_mode_end_saves_report` (`save_report` stubbed; expiry seen by the check calls it once).
- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_receive.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the names above in the three notebooks.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_receive.py tests/test_peers.py tests/test_control.py tests/test_approvals.py tests/test_guards.py tests/test_steering.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `"Ramabana sessions take notes, asks and replies from peers"`

### Task 5: The `peer-work` skill

**Files:**
- Create: `nbs/24_peer_work.ipynb` → `ramabana/peer_work.py` (module docstring is the skill, as in `nbs/09_coding_patterns.ipynb`)
- Modify: `pyproject.toml` `[project.entry-points.pyskills]`: `peer_work = "ramabana.peer_work"`
- Test: notebook cell

**Interfaces:**
- Produces: `ramabana.peer_work.__doc__`, the skill text. Task 6 copies it into `~/.claude/skills/peer-work/SKILL.md` (with front matter `name: peer-work`, a one-line `description`) and the Codex instructions.

- [ ] **Step 1: Write the test cell**: the doc names each of the five rules from spec §6 (repo rules first; agree the shape with the owner; no edits in another session's folders; proof means a test command with its output and, for UI, a Chrome for Testing screenshot path; the owner reviews the diff), the `changes:` / `proof:` reply lines, `ramabana tell --reply-to`, `ramabana peers --add-folder` after `/add-dir`, and that an ask needs the user unless work together mode is on with that sender. Assert those strings are present.
- [ ] **Step 2: Run it to fail.** Run: `uv run nbdev-test --path nbs/24_peer_work.ipynb`. Expected: FAIL.
- [ ] **Step 3: Write the skill text** in STE, grade 9, at most about 60 lines.
- [ ] **Step 4: Export, reinstall the entry point and run.** Run: `uv run nbdev-export && uv sync && uv run nbdev-test --path nbs/24_peer_work.ipynb && uv run pytest tests/test_skills.py -q`. Expected: PASS, and `peer_work` is in the skill list.
- [ ] **Step 5: Commit.** `"Add the peer-work skill"`

### Task 6: Hooks for Claude Code and Codex

**Files:**
- Create: `nbs/25_peer_hooks.ipynb` → `ramabana/peer_hooks.py`
- Modify: `nbs/19_setup.ipynb` (`run_cli`: `peer-hook`)
- Test: `tests/test_peer_hooks.py`

**Interfaces:**
- Consumes: Tasks 1–3, Task 5.
- Produces:
  - `@dataclass Adapter(kind, config: str, skill_path: str, session_env: str|None, wakes: bool)`. `ADAPTERS = {'claude': Adapter('claude', '~/.claude/settings.json', '~/.claude/skills/peer-work/SKILL.md', 'CLAUDE_CODE_SESSION_ID', True), 'codex': Adapter('codex', '~/.codex/hooks.json', '~/.codex/AGENTS.md', None, False)}`.
  - `hook_block(kind) -> dict`: the hook entries for that agent's config. Claude: `SessionStart`, `UserPromptSubmit`, `Stop` (sync), `Stop` (`"async": true, "asyncRewake": true`, command `ramabana peer-hook claude wait`), `SessionEnd`, `PreToolUse` with matcher `Edit|Write|NotebookEdit`. Codex: `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`, `PreToolUse` (apply_patch). Each command is `ramabana peer-hook <kind> <event>`.
  - `peer_hook(kind, event, data: dict, d=None) -> tuple[int, str, str]` (exit code, stdout, stderr). `main` reads stdin JSON and writes them out.
    - `session-start`: `register(d, kind, data['session_id'], [git_root(data['cwd'])], agent_pid())`. Returns `additionalContext`: your peer name and key, the live peers list, how to use `ramabana tell`, and (Codex, no `session_env`) `pass --session <id>`.
    - `prompt` (`UserPromptSubmit`): `take` unread → `additionalContext` with them as `peer_text`. If `together_off` ended a mode, add the saved report or the hint to run `ramabana report`.
    - `stop` (sync): unread → `{"decision": "block", "reason": <peer_text of each>}`, else `''`.
    - `wait` (async): exit at once (0) if `d/f'{key}.wait'` holds a live pid other than ours; else write our pid there, `wait_take(..., timeout=None, alive=lambda: (d/f'{key}.json').exists())`. On messages, exit 2 with them on stderr. Also, when `together_state` turns None after being on, run `ramabana report --save` in a subprocess before going on waiting.
    - `end`: `unregister`; remove the `.wait` file.
    - `pre-tool`: `folder_denial(tool_input path, key, all_peers())` → Claude: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}}`.
  - Hook text for an ask reminds the agent: ask the user first unless `together_state` is on with that sender.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_hooks.py`, with `RAMABANA_PEERS` set to `tmp_path`, calling `peer_hook` with fixture dicts: `test_session_start_registers_and_briefs`; `test_prompt_injects_unread_once`; `test_stop_blocks_on_unread_and_passes_when_empty`; `test_wait_exits_2_with_messages` (run `python -m ramabana.peer_hooks claude wait` as a subprocess with JSON on stdin; post a note; exit 2 and the note on stderr within 5 s); `test_second_waiter_exits_at_once`; `test_waiter_exits_on_unregister`; `test_pre_tool_denies_other_sessions_folder`; `test_prompt_ends_together_and_points_at_report`; `test_codex_session_start_says_pass_session`; `test_hook_import_is_light` (in a subprocess, `import ramabana.peer_hooks` leaves `ramabana.agent` out of `sys.modules`).
- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_hooks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `nbs/25_peer_hooks.ipynb`, and in `run_cli`: `if sys.argv[1:2] == ['peer-hook']: return peer_hooks.main(sys.argv[2:])`.
- [ ] **Step 4: Check the hook JSON shapes** against https://code.claude.com/docs/en/hooks.md (`UserPromptSubmit`, `SessionStart`, `PreToolUse` output) and https://developers.openai.com/codex/hooks. Fix any difference and pin it in a test.
- [ ] **Step 5: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_hooks.py -q`. Expected: PASS.
- [ ] **Step 6: Commit.** `"Add peer hooks for Claude Code and Codex"`

### Task 7: The morning report

**Files:**
- Create: `nbs/26_peer_report.ipynb` → `ramabana/peer_report.py`
- Modify: `nbs/19_setup.ipynb` (`run_cli`: `report`)
- Test: `tests/test_peer_report.py`

**Interfaces:**
- Consumes: Tasks 1–2, `mk_agent` and `Agent.oneshot(prompt, sp, job='summary')`.
- Produces:
  - `threads(rows) -> list[dict]`: one per thread: `asker, worker, ask, state, changes, proof`. `state` is `replied`, `not proven` (a reply with no `proof`), `refused`, `waiting` (no reply) or `stopped` (a `refused` event row).
  - `checked_changes(t, since) -> list[str]`: `changes` items marked `(not in git)` when a commit or path is not in `git log --since` of the worker's folders.
  - `table(ts) -> str`: a Markdown table with the columns `Asked by | Done by | What | Changed | Proof | State`.
  - `GLOSSARY: dict` (peer, note, ask, reply, thread, hop, work together mode, proof, budget) and `glossary(text) -> str`: only the terms that the report uses.
  - `summarise(ts, agent=None) -> tuple[str, str]`: the simple examples and the action list from one `summary` job call. The system prompt fixes STE grade 9, one sentence per example, and each action as "what to do: where". Waiting asks, `not proven` threads and `stopped` sessions are always action items.
  - `report(since, cfg=None, agent=None) -> str`: `# Night of <date>`, the table, `## What changed` (examples), `## Your actions`, `## Glossary`.
  - `save_report(since, cfg=None) -> Path`: `peers_dir/'reports'/f'{date:%Y-%m-%d}.md'`. It rebuilds only when the log has rows newer than the file.
  - `report_cli(argv)`: `ramabana report [--since T] [--save]`. `--since` defaults to the `started` of the latest `together_end` row.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_report.py`, using a fixture log with three threads (replied with proof, replied without proof, refused by hops) and a stubbed `summarise`: `test_threads_states`; `test_table_columns_and_rows`; `test_glossary_only_used_terms`; `test_actions_always_list_unproven_and_stopped`; `test_save_report_reuses_fresh_file`; `test_checked_changes_marks_missing_commit` (a temp git repo).
- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_report.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the names above. A failed `summary` call still saves the table, the actions it can derive, and the glossary, plus one line saying the examples are missing.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_report.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `"Add the morning report for work together mode"`

### Task 8: `ramabana setup peers` and the doctor

**Files:**
- Modify: `nbs/19_setup.ipynb` (`setup_cli`, `SETUP_USAGE`, `--doctor`)
- Test: `tests/test_peer_setup.py`

**Interfaces:**
- Consumes: Task 5 (skill text), Task 6 (`ADAPTERS`, `hook_block`).
- Produces:
  - `setup_peers(argv, ask=input, out=print, home=None) -> int`: `ramabana setup peers [--agent claude|codex|all] [--remove] [--yes]`. For each adapter: merge `hook_block` into its config (an entry is ours when its command starts with `ramabana peer-hook`; re-running changes nothing), write the skill or instructions file, show a `difflib` unified diff of each file, and write only after `y` (or `--yes`). `--remove` takes out only our entries. A missing config file is created. Malformed JSON stops with a message and writes nothing. For Codex, also print the line that it will ask to trust the new hooks on its next start.
  - `setup_cli`: `if argv[:1] == ['peers']: return setup_peers(argv[1:], ask, out)`.
  - `--doctor` gains one line for each adapter: `peers: claude hooks installed`, or `not installed: run ramabana setup peers --agent claude`.

- [ ] **Step 1: Write the failing tests** in `tests/test_peer_setup.py`, with `home=tmp_path`: `test_shows_diff_and_writes_on_yes`; `test_no_answer_writes_nothing`; `test_second_run_changes_nothing`; `test_keeps_users_other_hooks` (an existing unrelated `Stop` hook stays); `test_remove_takes_only_ours`; `test_bad_json_refuses`; `test_codex_writes_hooks_and_agents_md`; `test_doctor_reports_adapters`.
- [ ] **Step 2: Run to fail.** Run: `uv run pytest tests/test_peer_setup.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the names above.
- [ ] **Step 4: Export and run.** Run: `uv run nbdev-export && uv run pytest tests/test_peer_setup.py tests/test_setup.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `"Add ramabana setup peers for Claude Code and Codex"`

### Task 9: End-to-end check, docs and the full suite

**Files:**
- Create: `tests/test_peer_e2e.py`
- Modify: `nbs/index.ipynb` (a short "Talk between sessions" section: setup, `peers`, `tell`, `together`, `report`), `nbs/sidebar.yml`

- [ ] **Step 1: Write `test_two_sessions_work_together_and_report`**:
  - Set up a Ramabana `Control` on a `ScriptedBackend` agent and a fake Claude session (a registration plus `peer_hook` calls), both in a temp cfg.
  - Turn work together mode on for both, with each other as partner.
  - The Claude side sends an ask with `tell`. The Ramabana side runs the turn and replies with proof. The Claude side's `stop` hook blocks with the reply.
  - Then a scripted ping-pong runs until `limit_refusal` stops it.
  - Expiry builds the report (stubbed `summarise`), and its table shows one `replied` thread and one `stopped` row.
- [ ] **Step 2: Run it.** Run: `uv run pytest tests/test_peer_e2e.py -q`. Expected: PASS. If it fails, fix the owning task's code, not the test.
- [ ] **Step 3: Write the docs section** in `nbs/index.ipynb` (STE, grade 9). Check `nbs/index.ipynb` for stale references.
- [ ] **Step 4: Run everything.** Run: `uv run nbdev-prepare && uv run pytest -q -n auto`. Expected: both PASS with no new warnings.
- [ ] **Step 5: Commit.** `"Document peer talk and add the end-to-end test"`
