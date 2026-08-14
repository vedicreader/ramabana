"""Everything that runs a model: native output capture, the context window, and the backend the harness talks to.

## Native output

A local engine is a C++ library that writes to file descriptors 1 and 2 directly, so its
complaints never pass through Python and never reach a log handler. When a turn fails
because the model was handed more tokens than it can hold, the only evidence is on a
descriptor. This section reads that evidence and keeps the one line worth showing.

`captured` tees a descriptor rather than swallowing it: the bytes still reach the terminal
they were going to, and a copy lands in a buffer. It is serialised on a class lock, since
two threads redirecting descriptor 2 at the same time would restore each other's copies
and permanently detach the real one.

## Sizing a conversation

Every budget here is a fraction of the window rather than a constant, because the same
code serves a 4k local model and a 200k cloud one. A fixed 16k reserve against a 4k window
makes every turn "due for compaction", which is how an agent ends up compacting a
two-message conversation forever.

## Reading a conversation

Two backends are in play and their message shapes differ -- aidialog objects with
`content` parts, and provider dicts. Everything that inspects history goes through `_text`,
`_role` and `_calls` so the difference is confined to three functions.

`serialise` renders history as the tagged block a summarizer reads, clipping tool results
because they are almost all of the bulk and almost none of the meaning.

The summarizer's own window is the small one, so `summarise_prompt` fits the request into
a token budget rather than hoping. The instructions are never clipped away: an existing
checkpoint gets at most a quarter of the request and the newest transcript gets the rest.

`truncate_middle` keeps both ends of a value, since the informative parts of a path, an
error or a diff are at its edges. `surgical_history` uses it to render old history as a
compact DSL -- the deterministic alternative to summarising, for when no summarizer model
is available or its output cannot be trusted.

## Reorienting the model

After its context is rewritten, a model is told what just happened. Every clause is here
because leaving it out causes a specific failure: without the kernel sentence it re-imports
and rebuilds data that is still live, without the skills sentence it works from a
half-remembered skill, and without the last sentence it re-answers a question it already
answered -- because a summary reads like an instruction to resume.

## Notices on the way in

A submitted prompt earns notices before it reaches the model. These are cheap string
checks, and each one exists because of a failure people actually hit -- most of all the
approval notice: a person who types "go" after a long exchange is approving the thing under
discussion, not the four other things the model listed on the way there.

## Notebook context, last mile

A tagged notebook is sent whole whenever it fits. Only when it does not does the user's
per-cell policy take effect: cells marked `discard` go first, then the oldest `auto` cells,
and a `keep` cell is never dropped. The `fits` callable belongs to the backend, so the real
window of the selected model decides -- not an estimate made here.

## The compactor

`Compactor` decides when to compact and does it. It is deliberately not a callback on
either engine: compaction needs a second model call on a different, cheaper model, and then
it has to replace the first model's history -- two things neither backend's callback system
is shaped for. Keeping it out here also means the summary is available to write into the
notebook, which is the point.

## Answers, without the thinking

A reasoning model emits `<think>...</think>` inline whenever the runtime does not separate it
into a channel of its own. Every cheap job here reads a one-shot reply as data -- a label, a
summary, a completion to insert -- so the thinking has to come off before the caller sees it.
A classifier that returns the model's deliberation returns nothing.

Some models never emit the opening tag at all, because their chat template writes it into the
generation prompt and leaves the model to close it. That breaks any splitter looking for a
`<think>` to begin with: the deliberation arrives as ordinary reply text, and only the closing
tag comes back. It also happens once per *step*, so a turn that calls tools re-enters the
thought after every call. `answer_only` handles a finished reply, `ThinkFilter` handles a
streamed one, and the cheap jobs sidestep it entirely by asking not to think.

## Usage

`Usage` is one turn's token accounting, and it adds -- so a session total is `sum(usages)`
and the same object renders the status bar.

## Backend

`Backend` is the harness's whole view of a model: start it, send to it, stream from it,
count its tokens, replace its history. Nothing above this class knows whether the model is
a local engine or an HTTP API.

The contract that matters is that it does not raise. A model that cannot start, a turn that
fails mid-stream and an engine that returns nothing all produce a readable note and a
recorded problem, because the alternative is a traceback in a chat window.

## RishiBackend

Rishi runs every model, local or hosted, so there is one subclass. It translates a
`ModelSpec` into rishi's `Chat`, adapts per-runtime quirks (litert wants its token ceiling
and constrained decoding; MLX wants a separate completion-only conversation so a suggestion
never sees prior suggestions), and converts rishi's usage into `Usage`.

LiteRT models run on the GPU without being asked for it: rishi requests that backend by
default and warns its way down to the CPU on a machine whose build has no delegate. So
`RAMABANA_LITERT_BACKEND` is the way to *overrule* that -- `cpu` pins a model to the CPU,
`gpu` asks for what rishi would have asked for anyway -- and an explicit `backend=` (or
`eng_kw={'backend': ...}`) still takes precedence over both. `RISHI_LITERT_GPU=0` turns the
default off at the layer that owns it.

Docs: https://vedicreader.github.io/ramabana/runtime.html.md"""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_runtime.ipynb.

# %% auto #0
__all__ = ['MAX_KEEP', 'CHARS_PER_TOKEN', 'RESERVE', 'KEEP_RECENT', 'SUMMARY_PREFIX', 'SURGICAL_POLICY', 'SUMMARISE_SP',
           'SUMMARISE', 'UPDATE_SUMMARISE', 'REORIENT', 'Q_NOTICE', 'READ_NOTICE', 'APPROVAL_NOTICE', 'BTW_NOTICE',
           'ACTION_NOTICE', 'MAX_STEPS', 'ONESHOT_TOKENS', 'interesting', 'captured', 'capture', 'estimate_tokens',
           'threshold', 'should_compact', 'serialise', 'split_previous', 'summarise_prompt', 'truncate_middle',
           'surgical_history', 'reorient', 'prompt_notices', 'notices_block', 'compact_notebook_context', 'Compactor',
           'answer_only', 'prefills_think', 'ThinkFilter', 'Usage', 'Backend', 'use_chat', 'RishiBackend',
           'make_backend']

# %% ../nbs/01_runtime.ipynb #835f4984
import copy, os, re, sys, threading
from contextlib import contextmanager
from dataclasses import dataclass
from .core import agent_err, env, force_tags, tool_channel

# %% ../nbs/01_runtime.ipynb #3f4f3ba6
MAX_KEEP = 8_000        # tail kept per call; an engine that logs a lot must not eat memory
_NOISE = ('created tensorflow lite', 'xnnpack delegate', 'metal delegate', 'tflite','loading model', 'initialized', 'gpu delegate', 'w0000', 'i0000')
_SIGNAL = ('error', 'fail', 'exceed', 'exceeds', 'too long', 'out of memory', 'oom','invalid', 'refus', 'cannot', 'unsupported', 'abort')

# %% ../nbs/01_runtime.ipynb #a4f0dada
def interesting(text, limit=4):
    "The lines of captured output a person should see: complaints, not chatter."
    from fastcore.basics import uniqueify
    out = []
    for ln in (text or '').splitlines():
        s = ln.strip()
        if not s: continue
        low = s.lower()
        if any(n in low for n in _NOISE): continue
        if any(g in low for g in _SIGNAL): out.append(s)
    return uniqueify(out)[-limit:]


# %% ../nbs/01_runtime.ipynb #c5fce893
class _Tee:
    "One redirected descriptor: everything through a pipe, out to the original, and into a buffer."
    def __init__(self, fd):
        self.fd, self.buf, self.thread = fd, bytearray(), None
        self.saved = self.r = self.w = None
    def start(self):
        self.saved = os.dup(self.fd)              
        self.r, self.w = os.pipe()
        os.dup2(self.w, self.fd)
        os.close(self.w)
        self.w = None
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()
    def _pump(self):
        while True:
            try: b = os.read(self.r, 4096)
            except OSError: break
            if not b: break
            self.buf += b
            del self.buf[:-MAX_KEEP]
            try: os.write(self.saved, b)              # still goes where it was going
            except OSError: pass
    def stop(self):
        # the real descriptor goes back first, so a write during teardown lands somewhere real
        if self.saved is not None:
            try: os.dup2(self.saved, self.fd)
            except OSError: pass
        if self.r is not None:
            try: os.close(self.r)
            except OSError: pass
        if self.thread is not None: self.thread.join(timeout=1.0)
        if self.saved is not None:
            try: os.close(self.saved)
            except OSError: pass
        return self.buf.decode('utf-8', 'replace')

# %% ../nbs/01_runtime.ipynb #821d64c1
class captured:
    "Context manager: `with captured() as cap: ...`, then read `cap.text`."
    _lock = threading.Lock()   # two threads redirecting one descriptor would restore each other's copies
    def __init__(self, fds=(1, 2), enabled=None):
        self.fds = fds
        self.text = ''
        # through `env`, so the switch follows whatever prefix this application named
        self.enabled = ((env('NO_NATIVE_CAPTURE') or '').lower() not in ('1', 'true', 'yes')
                        if enabled is None else enabled)
        self._tees, self._held = [], False
    def __enter__(self):
        if not self.enabled: return self
        if not self._lock.acquire(timeout=0.5): return self
        self._held = True
        for fd in self.fds:
            t = _Tee(fd)
            try:
                sys.stdout.flush(); sys.stderr.flush()
                t.start()
                self._tees.append(t)
            except Exception: break
        return self
    def __exit__(self, *exc):
        parts = []
        for t in reversed(self._tees):
            try: parts.append(t.stop())
            except Exception: pass
        self._tees = []
        if self._held:
            self._held = False
            try: self._lock.release()
            except RuntimeError: pass
        self.text = ''.join(reversed(parts))
        return False

    @property
    def problems(self):
        "The captured lines worth reporting, as one string, or ''."
        return '\n'.join(interesting(self.text))

# %% ../nbs/01_runtime.ipynb #1b16a11e
def capture(fn, *a, **kw):
    "Call `fn`, returning `(result, captured_problem_text)`. Exceptions carry the text out too."
    cap, err, out = captured(), None, None
    with cap:
        try: out = fn(*a, **kw)
        except Exception as e: err = e
    if err is not None:   # after the block: the text does not exist until the pipe is drained
        err.native_output = cap.problems
        raise err
    return out, cap.problems

# %% ../nbs/01_runtime.ipynb #da1ec431
CHARS_PER_TOKEN = 4          # tau's estimate, for text no tokenizer has seen yet
RESERVE = 16_384             # headroom kept below the window: one full reply plus its tool results
KEEP_RECENT = 20_000         # tokens of recent conversation compaction does not touch
SUMMARY_PREFIX = 'Previous conversation summary:\n'
SURGICAL_POLICY = {'user': 2000, 'assistant': 150, 'call': 60, 'result': 35}

# %% ../nbs/01_runtime.ipynb #be51204d
def estimate_tokens(text, count=None):
    "Tokens in `text`: exact via `count` when a tokenizer is at hand, tau's chars/4 otherwise."
    if not text: return 0
    if count is not None:
        try: return count(text)
        except Exception: pass
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)

def threshold(ctx, reserve=RESERVE):
    "The token count at which a conversation should be compacted, or None when there is no window."
    if not ctx or ctx <= 0: return None
    return max(1, ctx - min(reserve, max(1, ctx // 4)))   # a quarter of the window, for small models

def should_compact(used, ctx, reserve=RESERVE):
    "Whether `used` tokens against a `ctx` window has crossed the line."
    t = threshold(ctx, reserve)
    return bool(t and used >= t)

# %% ../nbs/01_runtime.ipynb #33a7a74c
def _text(m):
    "The readable text of a message in either backend's shape."
    if hasattr(m, 'content') and not isinstance(m, dict):        # aidialog Msg
        return '\n'.join(str(p.text) for p in m.content if getattr(p, 'text', None))
    if not isinstance(m, dict): return str(m)
    c = m.get('content', '')
    if isinstance(c, str): return c
    out = []
    for p in c or []:
        if not isinstance(p, dict): continue
        if p.get('type') == 'text': out.append(p.get('text', ''))
        elif p.get('type') == 'tool_response': out.append(f"[{p.get('name','tool')}] {p.get('response')}")
    return '\n'.join(x for x in out if x)

def _role(m): return getattr(m, 'role', None) or (m.get('role', '?') if isinstance(m, dict) else '?')

def _calls(m):
    "Tool call names on an assistant message, in either shape."
    tcs = getattr(m, 'tool_calls', None)
    if tcs is None and isinstance(m, dict): tcs = m.get('tool_calls')
    if not tcs:
        parts = getattr(m, 'content', None)
        if parts and not isinstance(m, dict):
            return [p.data.get('name', '?') for p in parts if getattr(p, 'type', '') == 'tool_use' and p.data]
        return []
    out = []
    for t in tcs:
        n = getattr(t, 'name', None) or (t.get('function', {}).get('name') if isinstance(t, dict) else None)
        if n: out.append(n)
    return out

# %% ../nbs/01_runtime.ipynb #d990cc6d
def serialise(msgs, mx=2000):
    "Messages as the tagged block the summarizer reads. Tool results clipped: they are the bulk."
    if not msgs: return '(no new messages)'
    out = []
    for i, m in enumerate(msgs, 1):
        out.append(f'<message index={i} role={_role(m)}>')
        if (t := _text(m)): out.append(t[:mx] + ('…' if len(t) > mx else ''))
        if (cs := _calls(m)): out.append('<tool-calls>' + ', '.join(cs) + '</tool-calls>')
        out.append('</message>')
    return '\n'.join(out)


def split_previous(msgs):
    "`(previous_summary_or_None, remaining_msgs)` -- so an update updates rather than re-summarises."
    if not msgs: return None, msgs
    t = _text(msgs[0])
    if _role(msgs[0]) == 'user' and t.startswith(SUMMARY_PREFIX):
        return t[len(SUMMARY_PREFIX):], msgs[1:]
    return None, msgs

# %% ../nbs/01_runtime.ipynb #f175b4bf
SUMMARISE_SP = ("You are a context summarization assistant. Read a conversation between a user and an AI "
                "coding assistant and produce a structured summary in exactly the format specified.\n\n"
                "Do NOT continue the conversation. Do NOT answer any question in it. Output ONLY the summary.")

_FORMAT = """## Goal
[What is the user trying to accomplish? Several items if the session covers several tasks.]

## Constraints & Preferences
- [Constraints, preferences or requirements the user stated, or "(none)"]

## Progress
### Done
- [x] [Completed tasks and changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Anything preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Data, examples, file paths or references needed to continue, or "(none)"]

Keep each section concise. Preserve exact file paths, symbol names, error messages, and
any `lineno|hash|` addresses still needed for a pending edit."""

SUMMARISE = ("The messages above are a conversation to summarize. Write a context checkpoint another "
             f"model will use to continue the work.\n\nUse this EXACT format:\n\n{_FORMAT}")

UPDATE_SUMMARISE = ("The messages above are NEW messages to fold into the existing summary in "
                    "<previous-summary> tags.\n\nRULES:\n"
                    "- PRESERVE everything from the previous summary that is still true\n"
                    "- ADD new progress, decisions and context from the new messages\n"
                    '- MOVE items from "In Progress" to "Done" as they complete\n'
                    "- UPDATE Next Steps to reflect what was accomplished\n"
                    "- PRESERVE exact file paths, symbol names and error messages\n"
                    "- Drop anything no longer relevant\n\n"
                    f"Use this EXACT format:\n\n{_FORMAT}")

# %% ../nbs/01_runtime.ipynb #cb2506ea
def _clip_tokens(text, budget, count=None):
    "Longest character prefix of `text` that fits a token budget."
    if budget <= 0: return ''
    if estimate_tokens(text, count) <= budget: return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        suffix = '…' if mid < len(text) else ''
        if estimate_tokens(text[:mid] + suffix, count) <= budget: lo = mid
        else: hi = mid - 1
    return text[:lo] + ('…' if lo < len(text) else '')


def summarise_prompt(msgs, extra='', max_tokens=None, count=None):
    "The bounded prompt handed to the summarizer, choosing fresh or update instructions."
    prev, rest = split_previous(msgs)
    base = UPDATE_SUMMARISE if prev is not None else SUMMARISE
    if extra.strip(): base = f'{base}\n\nAdditional focus: {extra.strip()}'
    transcript = serialise(rest)
    def build(body, old=prev):
        p = f'<conversation>\n{body}\n</conversation>\n\n'
        if old is not None: p += f'<previous-summary>\n{old}\n</previous-summary>\n\n'
        return p + base
    if not max_tokens or estimate_tokens(build(transcript), count) <= max_tokens: return build(transcript)
    old = prev
    if old is not None: old = _clip_tokens(old, max(64, max_tokens // 4), count)
    fixed = build('', old)
    room = max(0, max_tokens - estimate_tokens(fixed, count) - 4)
    body = _clip_tokens(transcript, room, count)
    out = build(body, old)
    while body and estimate_tokens(out, count) > max_tokens:
        body = body[:-1]
        out = build(body + '…', old)
    return _clip_tokens(out, max_tokens, count)

# %% ../nbs/01_runtime.ipynb #5e86aad6
def truncate_middle(text, budget, count=None, mark=' … '):
    "Keep both ends of text inside a token budget."
    text = str(text or '')
    if estimate_tokens(text, count) <= budget: return text
    if budget <= estimate_tokens(mark, count): return _clip_tokens(mark, budget, count)
    lo, hi, best = 0, len(text), mark
    while lo <= hi:
        n = (lo + hi) // 2
        left = (n + 1) // 2
        candidate = text[:left] + mark + (text[-(n-left):] if n-left else '')
        if estimate_tokens(candidate, count) <= budget: best, lo = candidate, n + 1
        else: hi = n - 1
    return best

# %% ../nbs/01_runtime.ipynb #b9bff6f5
def _call_rows(m):
    "Canonical `(name, args)` calls from a backend assistant message."
    if not isinstance(m, dict): return []
    out = []
    for tc in m.get('tool_calls') or []:
        fn = tc.get('function') or {}
        out.append((fn.get('name', 'tool'), fn.get('arguments') or {}))
    content = m.get('content')
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get('type') == 'tool_call':
            out.append((part.get('name', 'tool'), part.get('arguments') or {}))
    return out


def surgical_history(msgs, policy=None, count=None):
    "Render old history as a compact, readable DSL while preserving tool evidence."
    policy = {**SURGICAL_POLICY, **(policy or {})}
    rows = []
    for m in msgs:
        role, text = _role(m), _text(m).strip()
        if role == 'user' and text:
            rows.append('§ ' + truncate_middle(text, policy['user'], count) + ' §')
        elif role == 'assistant':
            if text: rows.append('» ' + truncate_middle(text, policy['assistant'], count) + ' »')
            for name, args in _call_rows(m):
                call = f"▶ {name}({', '.join(f'{k}={v!r}' for k,v in args.items())})"
                rows.append(truncate_middle(call, policy['call'], count))
        elif role == 'tool':
            result = ' ¶ '.join(x.strip() for x in text.splitlines() if x.strip())
            rows.append('> ' + truncate_middle(result, policy['result'], count))
    return '\n'.join(rows)

# %% ../nbs/01_runtime.ipynb #83afe271
def reorient(kernel_alive=True, skills=()):
    "What the model is told immediately after its context is rewritten."
    live = ("**Your context was rewritten to fit the window, but the kernel process was not touched.** "
            "The user's namespace, imports and variables are all still live exactly as they were -- do "
            "not re-import anything, do not rebuild data, and do not re-run setup. Call `list_vars` if "
            "you need to see what is there."
            if kernel_alive else
            "**Your context was rewritten and the kernel has restarted with a clean namespace.** "
            "Rebuild variables on demand; do not assume anything is still bound.")
    sk = (f"Skill text you read earlier is gone from your context; re-read it with `read_skill` before "
          f"relying on it ({', '.join(skills)})." if skills else
          "Any skill text you read earlier is gone from your context; re-read it before relying on it.")
    return (f'<system-reminder>\n{live}\n\n{sk}\n\n'
            'The summary above describes work in flight. If the last thing the user asked has already '
            'been answered and nothing is open, do not resume or re-answer anything -- reply with one '
            'short line and wait.\n</system-reminder>')


REORIENT = reorient()

# %% ../nbs/01_runtime.ipynb #6c7288d4
Q_NOTICE = ('This prompt ends with a question mark, so it is a question. Make only the tool calls needed '
            'to answer it, then answer it, then stop -- do not start the work it implies.')
READ_NOTICE = ('This prompt asks you to read something. Read the target in full now, before composing any '
               'response: a notebook with `notebook_cells` then `view_cell`, a file with `view_file`. '
               'Never answer from assumed or remembered contents.')
APPROVAL_NOTICE = ('This bare approval covers exactly what was explicitly agreed, and nothing more. Before '
                   'acting, check that each thing you are about to do was confirmed by the user -- not '
                   'merely proposed, listed or summarised by you. If approval of an item is uncertain, it '
                   'is not approved: ask.')
BTW_NOTICE = ('This prompt begins with "BTW" and is a side request. Answer it first, then resume the '
              'previous task if it has unfinished items. It does not cancel that task.')
ACTION_NOTICE = ('This is an action request, not a request for instructions or a plan. Use the available '
                 'execution/editing tools now, retry corrected calls when one fails, verify the requested '
                 'result exists, and only then answer with the completed result.')

_APPROVALS = ('go', 'ok', 'okay', 'yes', 'yep', 'sure', 'do it', 'go ahead', 'proceed')


def prompt_notices(prompt):
    "Notices a submitted prompt earns, from aai-coding's `UserPromptSubmit` hook."
    p = (prompt or '').strip()
    out = []
    if p.endswith('?'): out.append(Q_NOTICE)
    if re.search(r'\b(please read|read the|have a look at)\b', p.lower()): out.append(READ_NOTICE)
    if re.sub(r'^\W+|[\s.!]+$', '', p.lower()) in _APPROVALS: out.append(APPROVAL_NOTICE)
    if p.lower().startswith('btw'): out.append(BTW_NOTICE)
    low = p.lower()
    if (re.match(r'^(create|make|scale|run|execute|fix|change|add|remove|rename|convert|save)\b', low)
            or re.search(r'\bas\s+[a-zA-Z_]\w*\s*$', p)):
        out.append(ACTION_NOTICE)
    return out


def notices_block(prompt):
    "The notices for `prompt` as one reminder to append to it, or `''`."
    ns = prompt_notices(prompt)
    return '' if not ns else '\n\n<system-reminder>\n' + '\n\n'.join(ns) + '\n</system-reminder>'

# %% ../nbs/01_runtime.ipynb #45fad4d6
def compact_notebook_context(prompt, fits):
    "Reduce a tagged notebook only when `prompt` does not fit; a `keep` cell is never removed."
    if not isinstance(prompt, str) or fits(prompt): return prompt
    match = re.search(r'<notebook(?P<attrs>[^>]*)>\n?(?P<body>.*?)\n?</notebook>', prompt, re.S)
    if not match: return prompt
    cells = list(re.finditer(r'<cell\b[^>]*\bcompact="(?P<mode>auto|keep|discard)"[^>]*>.*?</cell>',
                             match.group('body'), re.S))
    active = list(range(len(cells)))

    def rebuild(removed):
        omitted = [cells[n].group('mode') for n in sorted(removed)]
        body = '\n'.join(cells[n].group(0) for n in active if n not in removed)
        note = (f'<context-compacted omitted="{len(omitted)}" discard="{omitted.count("discard")}" '
                f'auto="{omitted.count("auto")}" />\n' if omitted else '')
        notebook = f'<notebook{match.group("attrs")}>\n{note}{body}\n</notebook>'
        return prompt[:match.start()] + notebook + prompt[match.end():]

    removed = set()
    for mode in ('discard', 'auto'):
        for n in active:
            if cells[n].group('mode') != mode: continue
            removed.add(n)
            candidate = rebuild(removed)
            if fits(candidate): return candidate
    return rebuild(removed)

# %% ../nbs/01_runtime.ipynb #4ee869b3
class Compactor:
    "Decides when to compact, and does it. Not a callback on either engine."

    def __init__(self,
                 reserve=RESERVE,
                 keep_recent=KEEP_RECENT,
                 auto=True,                  # compact automatically on crossing the threshold
                 kernel_alive=True,          # what the reorientation note may promise
                 on_compact=None,            # called with the compacted checkpoint once it exists
                 strategy='summary'):         # 'summary' | 'surgical' deterministic DSL
        self.reserve, self.keep_recent, self.auto = reserve, keep_recent, auto
        self.strategy = strategy
        self.kernel_alive, self.on_compact = kernel_alive, on_compact
        self.count = 0
        self.last = ''
        self.note = 'not compacted'

    def due(self, backend):
        "Whether `backend` has crossed its threshold."
        return should_compact(backend.used_tokens, backend.spec.ctx, self.reserve)

    def budget(self, ctx=0, overhead=0):
        "How much recent conversation to keep, for a window of `ctx` holding `overhead` besides."
        if not ctx: return self.keep_recent
        return min(self.keep_recent, max(256, max(256, ctx - overhead) // 2))

    def overhead(self, backend, msgs, count=None):
        "What the window holds that is not this conversation, by subtraction from `used_tokens`."
        used = getattr(backend, 'used_tokens', 0) or 0
        if not used: return 0
        return max(0, used - sum(estimate_tokens(_text(m), count) + 8 for m in msgs))

    def _keep(self, msgs, count=None, ctx=0, overhead=0):
        "The tail to keep uncompacted, newest-first until the budget runs out. Whole messages only."
        sizes = [estimate_tokens(_text(m), count) + 8 for m in msgs]
        budget = self.budget(ctx, overhead)
        if sizes: budget = min(budget, max(256, sum(sizes)//2))
        kept, used = [], 0
        for m, n in zip(reversed(msgs), reversed(sizes)):
            if used + n > budget and kept: break
            kept.append(m); used += n
        kept.reverse()
        # the tail starts at a user turn: a dangling tool call is rejected by some providers
        while kept and _role(kept[0]) != 'user': kept.pop(0)
        return kept

    def compact(self, backend, summariser, extra='', summary_ctx=0, summary_output=1024,
                summary_count=None):
        "Summarise `backend`'s conversation with `summariser(prompt, sp)` and replace it; the summary, or `''`."
        msgs = list(backend.hist or [])
        if not msgs:
            self.note = 'nothing to compact'
            return ''
        keep = self._keep(msgs, backend.count_tokens, getattr(backend.spec, 'ctx', 0),
                          self.overhead(backend, msgs, backend.count_tokens))
        older = msgs[:len(msgs) - len(keep)] if len(keep) < len(msgs) else msgs
        if not older:
            self.note = 'everything is recent; nothing to compact'
            return ''
        if self.strategy == 'surgical':
            text = surgical_history(older, count=backend.count_tokens)
            head = SUMMARY_PREFIX + text + '\n\n' + reorient(self.kernel_alive)
            try: backend.replace_hist(head, keep)
            except Exception as e:
                self.note = f'compaction checkpoint written but history not replaced ({agent_err(e)})'
                return text
            self.count += 1; self.last = text
            self.note = f'surgically compacted {len(older)} message(s), kept {len(keep)}'
            if self.on_compact:
                try: self.on_compact(text)
                except Exception: pass
            return text
        # the system prompt and the output share the window with this request
        input_budget = None
        if summary_ctx:
            sp_tokens = estimate_tokens(SUMMARISE_SP, summary_count)
            input_budget = max(128, summary_ctx - summary_output - sp_tokens - 64)
        try:
            prompt = summarise_prompt(older, extra, input_budget, summary_count)
            text = (summariser(prompt, SUMMARISE_SP) or '').strip()
        except Exception as e:
            self.note = f'compaction failed ({agent_err(e)})'
            return ''
        if not text:
            self.note = 'the summarizer returned nothing; conversation left alone'
            return ''
        head = SUMMARY_PREFIX + text + '\n\n' + reorient(self.kernel_alive)
        try: backend.replace_hist(head, keep)
        except Exception as e:
            self.note = f'compaction summary written but history not replaced ({agent_err(e)})'
            return text
        self.count += 1
        self.last = text
        self.note = f'compacted {len(older)} message(s), kept {len(keep)}'
        if self.on_compact:
            try: self.on_compact(text)
            except Exception: pass
        return text

# %% ../nbs/01_runtime.ipynb #a3e427bf
def answer_only(text):
    "A one-shot reply with the model's thinking removed, however the runtime left it."
    from rishi.core import split_think
    out, _ = split_think(text or '')
    if '</think>' in out: out = out.partition('</think>')[2]
    if '<think>' in out: out = out.partition('<think>')[0]
    return out.strip()


# %% ../nbs/01_runtime.ipynb #b3f10a21
def prefills_think(chat):
    "Does this model's chat template open a `<think>` block and leave the model to close it?"
    tok = getattr(chat, 'tokenizer', None)
    if tok is None: return False
    try: p = tok.apply_chat_template([{'role': 'user', 'content': 'x'}], add_generation_prompt=True, tokenize=False)
    except Exception: return False
    return '<think>' in p and '</think>' not in p.rsplit('<think>', 1)[-1]


class ThinkFilter:
    "Drop a template-opened thinking block out of a raw chunk stream; a tool call re-arms it."
    TAG = '</think>'

    def __init__(self): self.thinking, self.buf, self.thought, self.answer = True, '', 0, 0

    def _tool(self, o):
        parts = o.get('content') or [] if isinstance(o, dict) else []
        return any(isinstance(p, dict) and p.get('type') == 'tool_call' for p in parts)

    def __call__(self, chunks):
        "Filter raw chunk dicts, yielding the same shape back."
        from rishi.core import resp_text
        for o in chunks:
            if self._tool(o): self.thinking, self.buf = True, ''; yield o; continue
            if not self.thinking: self.answer += len(resp_text(o)); yield o; continue
            if not (txt := resp_text(o)): yield o; continue
            self.buf += txt; self.thought += len(txt)
            if (k := self.buf.find(self.TAG)) < 0: self.buf = self.buf[1 - len(self.TAG):]; continue
            self.thinking, out, self.buf = False, self.buf[k + len(self.TAG):].lstrip('\n'), ''
            if out: self.answer += len(out); yield {'content': [{'type': 'text', 'text': out}]}


# %% ../nbs/01_runtime.ipynb #e4819aa1
MAX_STEPS = 40
ONESHOT_TOKENS = 1024     # a cheap job's default output cap

@dataclass
class Usage:
    model:str=''; input:int=0; output:int=0; total:int=0; cached:int=0
    cache_write:int=0; reasoning:int=0; cost:float=0.; turns:int=0
    def __add__(self,o):
        if o is None: return self
        fs=('input','output','total','cached','cache_write','reasoning','cost','turns')
        return Usage(model=o.model or self.model,**{k:getattr(self,k)+getattr(o,k) for k in fs})
    def __radd__(self,o): return self if o in (None,0) else self+o
    def __sub__(self,o):
        "What this counter has added since `o`. A backend counts cumulatively; a turn is a delta."
        if o is None: return self
        fs=('input','output','total','cached','cache_write','reasoning','cost','turns')
        return Usage(model=self.model or o.model, **{k:max(0, getattr(self,k)-getattr(o,k)) for k in fs})
    def __repr__(self):
        p=[f'{self.total:,} tok',f'in {self.input:,}',f'out {self.output:,}']
        if self.cached:p.append(f'cached {100*self.cached/max(self.input,1):.0f}%')
        if self.reasoning:p.append(f'thought {self.reasoning:,}')
        if self.cost:p.append(f'${self.cost:.4f}')
        if self.model:p.append(self.model.split('/')[-1])
        return ' · '.join(p)
    def dict(self): return dict(self.__dict__)

# %% ../nbs/01_runtime.ipynb #af66f277
class Backend:
    kind='?'
    def __init__(self,spec,sp='',tools=(),approve=None,tool_max_len=None,shared=False,**kw):
        self.spec,self.sp,self.tools,self.approve=spec,sp,list(tools),approve
        self.tool_max_len,self.shared,self.kw=tool_max_len,shared,kw
        self.chat,self.use,self.note=None,Usage(model=spec.model_id),'not started'
        self.problems,self.last_native,self._tried=[], '', False
        self._resume_hist=None
        self.lock=threading.Lock()
    @property
    def ready(self): return self.chat is not None
    @property
    def busy(self): return self.lock.locked()
    @property
    def hist(self): return getattr(self.chat,'hist',[]) if self.chat else []
    def problem(self,text):
        text=(text or '').strip()
        if text and (not self.problems or self.problems[-1]!=text): self.problems.append(text)
        del self.problems[:-20]
        return text
    def _failed(self,what,e):
        native=getattr(e,'native_output','') or ''
        self.note=f'{self.spec.name} {what} ({agent_err(e)})'+(f' -- {native}' if native else '')
        return self.problem(self.note)
    def start(self):
        if self._tried:return self.chat
        self._tried=True
        try:
            self.chat=self._start()
            if self._resume_hist is not None:
                self.restore_hist(self._resume_hist); self._resume_hist=None
            self.note=f'{len(self.tools)} tools'
        except Exception as e:self.chat=None; self._failed('unavailable',e)
        return self.chat
    def retry(self): self._tried,self.chat=False,None; return self.start()
    def set_approve(self,approve):
        self.approve=approve
        if self.chat:self.chat.approve=approve
        return self
    def refresh(self,sp,tools):
        self.sp,self.tools=sp,list(tools)
        if self.chat:self._refresh(); self.note=f'{len(self.tools)} tools'
        return self
    def close(self):
        if aux:=getattr(self,'_oneshot_chat',None):
            try:aux.close()
            except Exception:pass
            self._oneshot_chat=None
        if self.chat:
            try:self.chat.close()
            except Exception:pass
            self.chat=None
    def cancel(self):
        if not self.chat:return False
        try:self.chat.cancel(); return True
        except Exception:return False
    def send(self,msg,**kw):
        if self.start() is None:return self.note
        with self.lock:
            for again in (True,False):
                try:
                    out=self._send(msg,**kw); self.use=self._usage()
                    self._check_reply(out)
                    return out or self._empty()
                except Exception as e:
                    if not (again and self._recover(e)):return self._failed('failed',e)
    def stream(self,msg,**kw):
        if self.start() is None:yield self.note; return
        with self.lock:
            for again in (True,False):
                n,buf=0,[]
                try:
                    for c in self._stream(msg,**kw): n+=len(c or ''); buf.append(c or ''); yield c
                    self.use=self._usage()
                    self._check_reply(''.join(buf))
                    if not n:yield self._empty(True)
                    return
                except Exception as e:
                    # only before anything reached the screen: a retry cannot unsay a chunk
                    if not (again and not n and self._recover(e)):
                        yield f'\n\n{self._failed("failed",e)}'; return
    def _recover(self,e):
        "Fix what made `e` happen, if this backend knows how, so one retry is worth taking. No by default."
        return False
    def _check_reply(self,text):
        "Look at a finished reply for a failure the transport could not raise. Nothing by default."
        return text
    def _empty(self,strict=False):
        why=f'{self.spec.name} returned nothing'+(f' -- {self.last_native}' if self.last_native else '')
        return self.problem(why) if strict else (f'({why})' if self.last_native else '(no reply)')
    def oneshot(self,prompt,sp='',max_tokens=None):
        if self.start() is None or not self.lock.acquire(False):return ''
        try:return answer_only(self._oneshot(prompt,sp,max_tokens) or '')
        except Exception as e:self._failed('one-shot failed',e); return ''
        finally:self.lock.release()
    def spawn(self,sp='',tools=(),**kw): raise NotImplementedError
    def replace_hist(self,summary,keep=()):
        if not self.chat:raise RuntimeError('nothing to compact: the model is not running')
        self._replace_hist(summary,list(keep)); return self
    def snapshot_hist(self):
        "A detached model-history checkpoint suitable for an in-process branch."
        return copy.deepcopy(list(self.hist))
    def resume_hist(self,hist):
        "Restore canonical history now, or after this backend starts lazily."
        if self.chat:return self.restore_hist(hist)
        self._resume_hist=copy.deepcopy(list(hist or [])); return self
    def restore_hist(self,hist):
        "Restore a checkpoint and rebuild provider conversation state."
        if not self.chat:raise RuntimeError('nothing to restore: the model is not running')
        self.chat.hist[:]=copy.deepcopy(list(hist or []))
        recreate=getattr(self.chat,'_recreate_conv',None)
        if recreate:recreate()
        return self
    def revise_last_assistant(self,text):
        "Replace the last prose assistant message in a restored checkpoint."
        if not self.chat:raise RuntimeError('nothing to revise: the model is not running')
        msg=next((m for m in reversed(self.chat.hist) if isinstance(m,dict) and m.get('role')=='assistant' and not m.get('tool_calls')),None)
        if msg is None:raise ValueError('checkpoint has no assistant response')
        msg['content']=str(text)
        msg.pop('channels',None); msg.pop('usage',None)
        recreate=getattr(self.chat,'_recreate_conv',None)
        if recreate:recreate()
        return self
    def count_tokens(self,text):
        try:return self.chat.count_tokens(text or '') if self.chat else max(1,(len(text or '')+3)//4)
        except Exception:return max(1,(len(text or '')+3)//4)
    @property
    def used_tokens(self):
        """What the window holds now, which every engine reports for itself.

        An agent harness used to report billing volume instead: Claude Code re-reads its cached
        prompt on every internal step and folds those cache reads into `total_tokens`, which
        over-stated a two-message conversation by 6.6x, while cursor reported nothing at all and
        sat at zero. Both are measured at the source from rishi 0.1.12, which is the floor.
        """
        try:return self.chat.token_count if self.chat else 0
        except Exception:return self.use.total
    @property
    def pct_full(self):return self.used_tokens/max(self.spec.ctx,1)
    def pending_tokens(self,msg):
        try:return self.count_tokens(self.chat.render(msg)) if self.chat and hasattr(self.chat,'render') else self.count_tokens(str(msg))+8
        except Exception:return self.count_tokens(str(msg))+8
    def projected_tokens(self,msg):return self.used_tokens+self.pending_tokens(msg)
    def fits(self,msg,reserve=None):
        if not self.spec.ctx:return True
        reserve=min(1024,max(128,self.spec.ctx//4)) if reserve is None else max(0,reserve)
        return self.projected_tokens(msg)<=max(1,self.spec.ctx-reserve)
    def _start(self):raise NotImplementedError
    def _send(self,msg,**kw):raise NotImplementedError
    def _stream(self,msg,**kw):raise NotImplementedError
    def _oneshot(self,prompt,sp,max_tokens):raise NotImplementedError
    def _replace_hist(self,summary,keep):raise NotImplementedError
    def _usage(self):return self.use
    def _refresh(self):raise NotImplementedError

# %% ../nbs/01_runtime.ipynb #4c988345
#: What builds a model conversation, and the one seam a recording replaces. `None` is rishi's
#: own `Chat`, which is what every application gets.
_MK_CHAT = None

@contextmanager
def use_chat(f):
    "Build model conversations with `f` for the duration, instead of rishi's `Chat`."
    global _MK_CHAT   # process-global, which is why this is a block and not a setting
    old, _MK_CHAT = _MK_CHAT, f
    try: yield f
    finally: _MK_CHAT = old


class RishiBackend(Backend):
    kind='rishi'
    def __init__(self,*a,max_steps=MAX_STEPS,**kw):
        self.max_steps,self._prefill=max_steps,None; super().__init__(*a,**kw)
    @property
    def prefilled_think(self):
        "Whether this model's template opens a thinking block the model has to close."
        if self._prefill is None:self._prefill=prefills_think(self.chat)
        return self._prefill
    def _runtime_kw(self):
        import os
        kw={**getattr(self.spec, 'config', {}), **self.kw}
        if key_env := kw.pop('api_key_env', None): kw['api_key'] = os.environ.get(key_env)
        # only `remote` takes the keyword; for the local engines tag calls are the protocol
        if self.spec.runtime=='remote' and tool_channel(self.spec)=='tags': kw.setdefault('tool_mode','tags')
        if self.spec.runtime=='litert':
            eng=dict(kw.pop('eng_kw',{}) or {})
            # rishi takes backend itself; inside eng_kw it arrives twice and no litert model loads.
            if 'backend' not in eng and 'backend' not in kw and (backend := env('LITERT_BACKEND')):
                from litert_lm import Backend as LB
                backends = {'cpu': LB.CPU, 'gpu': LB.GPU}
                if backend.lower() not in backends:
                    raise ValueError(f'unknown LiteRT backend {backend!r}; use cpu or gpu')
                kw['backend'] = backends[backend.lower()]()
            eng.setdefault('max_num_tokens',self.spec.ctx)
            kw['eng_kw']=eng
            if conv := dict(kw.pop('conv_kw',{}) or {}): kw['conv_kw']=conv   # rishi constrains a tool call itself
        return kw
    def _start(self):
        from rishi import Chat
        # a hand-built `ModelSpec` never passed through `resolve`, which installs this shim
        if self.spec.model_id.startswith('claude_code/'):
            from .core import _install_toolslm_funccall
            _install_toolslm_funccall()
        return (_MK_CHAT or Chat)(self.spec.model_id,runtime=self.spec.runtime,sp=self.sp,tools=self.tools,
                    approve=self.approve,tool_max_len=self.tool_max_len,max_steps=self.max_steps,
                    ctx_limit=self.spec.ctx,**self._runtime_kw())
    def spawn(self,sp='',tools=(),**kw):
        if self.start() is None:raise RuntimeError(self.note)
        shared={'engine':self.chat.engine} if self.spec.local and hasattr(self.chat,'engine') else {}
        return type(self)(self.spec,sp=sp,tools=tools,tool_max_len=self.tool_max_len,
                          max_steps=self.max_steps,shared=True,**shared,**kw)
    def _turn_kw(self, kw):
        "Apply hosted turn controls at the layer Rishi owns; Chat.__call__ only accepts generation controls."
        kw = dict(kw or {})
        effort = kw.pop('reasoning_effort', None)
        if effort is not None and hasattr(self.chat, 'reasoning_effort'):
            self.chat.reasoning_effort = effort
        return kw
    def _send(self,msg,**kw):
        # FastLLM's Claude Code transport is stream-only
        if self.spec.model_id.startswith('claude_code/'): return answer_only(''.join(self._stream(msg, **kw)))
        from rishi.core import resp_text
        return answer_only(resp_text(self.chat(msg,**self._turn_kw(kw))))
    #: What a transport says when it will not carry the tool schemas. An enterprise policy is the
    #: reason; the wording is the SDK's, and it arrives under several of these at once.
    MCP_REFUSED=('mcp','strict_mcp_config','allowed_tools','disallowed','not permitted','policy')
    def _recover(self,e):
        """Learn that this model's wire tool channel is closed, so later turns stop trying it.

        A managed configuration at one of the three documented paths is detected before the first
        request, by `claude_tags`. One at a path nobody documented, a plugin that failed to
        register, a version that dropped the field -- those are only ever learned from the failure
        they cause, and learning it here is what keeps the cost at one turn instead of every turn.

        The chat is rebuilt rather than reconfigured: `_runtime_kw` reads the channel when the
        chat is constructed, so a live one goes on sending schemas that are already being refused.
        """
        if not self.tools or tool_channel(self.spec)=='tags':return False
        if not any(s in f'{e}'.lower() for s in self.MCP_REFUSED):return False
        force_tags(self.spec.model_id,agent_err(e))
        self.problem(f'{self.spec.name}: the wire refused the tool schemas, so they now travel in '
                     f'the system prompt instead ({agent_err(e)})')
        hist=self.hist
        self.close(); self.retry()
        if self.chat is None:return False
        if hist:self.restore_hist(hist)
        return True
    def _check_reply(self,text):
        """Report a tag call that came back as prose, which is what the tags channel costs.

        On the wire a malformed call is a transport error and something raises. In the prompt it is
        just text, and the failure is silent: `parse_tool_tags` matches complete blocks, so an
        unclosed or misspelled tag stays in the reply and reads to the user as the model discussing
        a call it never made.

        This is a floor on how often the channel fails rather than a count of it. A well-formed
        block holding bad JSON is dropped by `mk_tag_tc` and leaves nothing behind to find, and
        counting those needs a hook rishi does not have yet. A number that is too low is still the
        difference between knowing this channel is costing calls and guessing.
        """
        if tool_channel(self.spec)=='tags' and '<tool_call' in (text or ''):
            self.problem(f'{self.spec.name}: a <tool_call> block came back as prose rather than a '
                         'call, so this model is not punctuating the tags channel reliably')
        return text
    def _stream(self,msg,**kw):
        kw=self._turn_kw(kw)
        if not self.prefilled_think:yield from self.chat(msg,stream=True,**kw); return
        # the thought is indistinguishable from the reply until the close, so filter the raw
        # chunks and hand the rest to rishi's own renderer
        from rishi.core import StreamFormatter
        f=ThinkFilter()
        yield from StreamFormatter().format_stream(f(self.chat(msg,stream='raw',**kw)))
        # "returned nothing" is true but useless, so say what happened instead
        if f.thought and not f.answer:
            self.problem(f'{self.spec.name} spent the whole turn thinking ({f.thought} characters) '
                         'and never answered; route `turn` to a larger model, or raise its output cap')
    def _oneshot(self,prompt,sp,max_tokens):
        # `think=False` everywhere: a cheap job's whole budget can be 32 tokens
        if self.spec.runtime!='mlx':
            return self.chat.oneshot(prompt,sp,think=False,max_tokens=max_tokens or ONESHOT_TOKENS)
        # a completion-only MLX conversation, rewritten in place so rishi can reuse the KV cache
        if getattr(self,'_oneshot_chat',None) is None:
            if not hasattr(self.chat,'engine'):   # nothing to share: a replayed chat has no engine
                return self.chat.oneshot(prompt,sp,think=False,max_tokens=max_tokens or ONESHOT_TOKENS)
            from rishi import Chat
            self._oneshot_chat=Chat(self.spec.model_id,runtime='mlx',engine=self.chat.engine,think=False,
                                    sp=sp,ctx_limit=self.spec.ctx,max_output_tokens=ONESHOT_TOKENS)
        # `c.sp=`, not `reconfigure`, which rebuilds backend state and drops MLX's cache
        c=self._oneshot_chat; c.sp=sp; c.hist[:]=[c.mk_msg(prompt)]
        from rishi.core import resp_text
        # always an explicit cap: this conversation is reused across jobs
        return resp_text(c._model_step(max_tokens or ONESHOT_TOKENS))
    def _replace_hist(self,summary,keep):
        # a replayed conversation has neither; `Compactor` catches the refusal and says so
        if not hasattr(self.chat,'_recreate_conv'):
            raise RuntimeError(f'{type(self.chat).__name__} cannot have its history replaced')
        self.chat.hist[:]=self.chat.mk_msgs([summary,*keep]); self.chat._recreate_conv()
    def _usage(self):
        # a replay spent no tokens, so zeros are the truthful answer
        if (u:=getattr(self.chat,'use',None)) is None: return Usage(model=self.spec.model_id)
        return Usage(model=u.model or self.spec.model_id,input=u.prompt_tokens,output=u.completion_tokens,
                     total=u.total_tokens,cached=u.cached_tokens,cost=u.cost,turns=u.n)
    def _refresh(self):
        self.chat.reconfigure(sp=self.sp,tools=self.tools)

# Dead names from when llama.cpp and FastLLM were separate backends.
def __getattr__(name):
    if name in ('LlamaBackend','FastllmBackend'):
        import warnings
        warnings.warn(f'{name} is a deprecated alias for RishiBackend; model execution goes '
                      'through Rishi for every runtime. Use RishiBackend.',
                      DeprecationWarning, stacklevel=2)
        return RishiBackend
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

def make_backend(spec,**kw):return RishiBackend(spec,**kw)
