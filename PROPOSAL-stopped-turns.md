# Record a turn that was stopped

A turn that is cancelled, or whose stream is abandoned, is not written to the history log. The
prompt and every chunk already streamed are lost. The conversation cannot be found again after a
restart, because as far as the log is concerned it never happened.

This proposes recording those turns and marking them, rather than discarding them.

## The fault

`Agent.stream` and `Agent.ask` are the patched versions in `nbs/03_agent.ipynb`, cell `1c649440`.
Both carry the docstring "Cancelled output is not persisted", so the behaviour is deliberate.

`Agent._remember` is the only writer to `<history_name>-history.jsonl`. It is reached from
`_finish` on success, and from the `except Exception` handlers on failure. Every other exit from a
turn writes nothing:

- `if run.cancelled: run.finish(); return`, before the stream starts.
- `if run.cancelled: break`, then `run.finish()` with no `_remember`.
- `if run.cancelled: run.finish(); return`, inside `except Exception`.
- `GeneratorExit`. It derives from `BaseException`, so `except Exception` does not see it. A caller
  that stops iterating and drops the generator loses the turn with no handler running at all.

The last one is reached in normal use. `leela/blocks/agent/threads.py`, `TurnRunner._work`, returns
out of `for chunk in stream` on an unaccepted turn, which abandons the generator.

Measured against the installed package with `ramabana.testing.fake_agent`:

| how the turn ended | rows written |
|---|---|
| ran to completion | 1 |
| abandoned after one chunk | 0 |
| cancelled mid-stream | 0 |

## Why the rule exists

`Agent.resume_session` rebuilds model context from the log. Each turn becomes a `user` message from
`prompt` and an `assistant` message from `activity` plus `reply`. A half-streamed reply would go
back to the model as a complete assistant turn, and a tool call recorded without its result would
go back as though it had one.

That is a reason to keep a stopped turn out of the context. It is not a reason to keep it out of
the record. The two are the same field today, which is the whole of the defect.

## The proposal

**1. Give a turn row a `state`.** `_remember` takes `state='complete'` and writes it. The values
are `complete`, `failed`, `cancelled` and `abandoned`. A row written before this change has no
`state` and reads as `complete`, so nothing already on disk changes meaning.

**2. Persist on every exit, exactly once.** A local flag, and a `finally` that catches what
`except Exception` cannot:

```python
@patch
def stream(self:Agent, prompt, on_registered=None, **kw):
    "One registered turn as markdown chunks. A stopped turn is recorded, and not replayed."
    run, out, kept = self._new_run(prompt), [], False
    def keep(state, text='', error=''):
        nonlocal kept
        if kept: return
        kept = True; self._remember(prompt, text, error, state=state)
    if self.start() is None:
        run.finish('failed'); yield self.note; return
    backend = self._be('turn')
    if not run.start(backend): return
    try:
        if on_registered is not None: on_registered(run)
        if run.cancelled: run.finish(); keep('cancelled'); return
        with run_context(run):
            outgoing = self._prepare(prompt)
            for chunk in backend.stream(outgoing, run=run, **kw):
                if run.cancelled: break
                chunk = _stream_chunk(out, chunk)
                if chunk: out.append(chunk); yield chunk
        run.finish()
        if run.cancelled: keep('cancelled', ''.join(out))
        else: kept = True; self._finish(''.join(out), prompt)
    except Exception as e:
        if run.cancelled: run.finish(); keep('cancelled', ''.join(out)); return
        run.finish('failed')
        self.note = f'the assistant failed ({agent_err(e)})'
        keep('failed', self.note, agent_err(e))
        yield f'\n\n{self.note}'
    finally:
        keep('abandoned', ''.join(out))
```

`kept = True` before `_finish` is what stops the success path writing twice, because `_finish`
calls `_remember` itself. The `finally` is what covers `GeneratorExit`, `KeyboardInterrupt` and
`SystemExit`. `ask` takes the same treatment at its two `run.cancelled` returns.

**3. Replay the same set as today.** `resume_session` filters on the new field:

```python
REPLAYED = ('complete', 'failed')
turns = [t for t in self.history
         if t.get('session') == picked['id'] and t.get('state', 'complete') in REPLAYED]
```

A failed turn is replayed now and keeps being replayed. A cancelled or abandoned turn is new to the
log and is not replayed. The context a resume builds is byte-identical to the context it builds
today, for every log that exists.

**4. Leave the listing alone.** `Agent.sessions` groups every row, so a stopped turn appears in a
picker without further change. `picked['turns']` counts it, which is correct: it is a turn that
happened.

## What this does not change

- No new file, and no new directory. One field on a row that is already written.
- `_remember` still writes only at the end of a turn. A hard kill of the process still loses the
  turn in flight. That is a separate change and is not proposed here.
- Nothing about the log's size or retention.

## Tests

In `nbs/04_testing.ipynb`'s idiom, driven by `fake_agent`:

1. A turn abandoned after one chunk is in the log, with `state == 'abandoned'` and the chunk it
   streamed as its `reply`.
2. A turn cancelled mid-stream is in the log, with `state == 'cancelled'`.
3. A turn that completes is in the log once, not twice.
4. Resuming a session holding a cancelled turn puts back the same messages as resuming the same
   session with that row deleted.
5. A row with no `state` field is replayed.

## Leela's side

None of this needs a change in Leela. `TurnRunner._work` keeps abandoning the generator on an
unaccepted turn, and the `finally` now records what it abandoned. The one thing Leela may want
afterwards is to show `state` in the history list, so a stopped conversation is distinguishable from
a finished one before it is opened.
