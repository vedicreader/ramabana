# A canvas is a host

A canvas is a document that runs: prose, code cells, embedded components and simulations in one
markdown file, where each thing recomputes when what it reads changes. Leela has a working one on
`claude/dynamic-document-canvas-ohgfud`, in `leela/blocks/canvas/`, with a scripted stand-in where
the model goes. See `docs/canvas.md` in that branch.

This proposes what the agent half needs: a capability group in shalya, and two behaviours here.

## What the canvas needs from an agent

The helper in the canvas has eight tools and nothing else.

| tool | does |
|---|---|
| `canvas_read` | the document as it stands: every brick, its kind, its bindings, what it defines |
| `canvas_insert` | a new brick at a position |
| `canvas_replace` | rewrite one brick, by id |
| `canvas_remove` | take a brick out, by id |
| `canvas_bind` | point one port of one brick at an expression |
| `canvas_run` | run a code brick and let the dataflow settle |
| `canvas_answer` | prose written back into the document, attached to the question that asked for it |
| `canvas_values` | read names out of the live namespace |

All eight go through one function on Leela's side, which is also what a person's own edits go
through. There is no second path into the document.

## Where they belong

In shalya, as a group. `Host.provides` is the only way to ask what a host supports, and a document
the agent can edit in place is a capability a host either has or does not.

`NotebookHost` is the nearest existing group, and it is not this one. It lists cells and appends
them. It has no notion of a binding, a port, or a value handed back by a component, and a canvas is
those three.

```python
class CanvasHost(Capability):
    "A document the agent can read, edit in place, and evaluate."
    group = 'canvas'
```

Eight abstract methods, one per tool. A host that declares the group writes all eight or refuses to
be built, which is shalya's existing rule.

`tools_for` gains the group. Nothing in ramabana changes for this part.

## What ramabana needs to change

Two things, both small, both useful outside a canvas.

### 1. Steering that lands between steps

Leela steers through `Interventions.queue_steer` and `consume_steer` in
`leela/blocks/agent/ai.py`. That queue is drained at an approval checkpoint. A turn in autopilot,
or a turn whose tools are all reads, has no checkpoints, so steering waits for a turn that may
never pause.

The canvas needs steering taken at every step boundary, whether or not a call is waiting for
approval. `consume_steer` is already the right shape. What is missing is a call to it in the step
loop, and a `steering` event on the stream so the client can show that it landed.

Proposed: `Agent.stream` checks a steer source once per step, folds any text into the next model
call as a user message, and emits `('steer', text)`. The source is a callable passed in, so the
queue stays where it is and ramabana keeps no state.

This is a strict addition. A turn with no steer source behaves as it does now.

### 2. A trail

The canvas carries the last twelve questions, each with the brick it was asked from and the text
that was selected. A follow-up question then needs no preamble, because "why is that one cheaper"
resolves against the row the person had just clicked.

That is not canvas-specific. Every inline assistant has it: the anchor a question was asked from is
context, and it is thrown away today.

Proposed: `Agent.trail`, a bounded deque of `{question, anchor, selection}`, appended by `ask` and
`stream` when the caller passes an anchor, and compiled into the briefing by `compile_context`
alongside `memory_context`. Bounded, so it cannot grow the context without limit. Empty by default,
so a caller that passes no anchor sees no change.

## What this does not propose

- Nothing about the document format. A canvas file is markdown, and Leela owns it.
- Nothing about the dataflow. Which cells rerun when a name moves is Leela's, and it is `defs_of`,
  `reads_of` and `downstream` in `leela/blocks/canvas/doc.py`.
- No change to approvals. A canvas edit is a write, and it goes in front of a person by the rules
  already there.

## Order

1. `CanvasHost` in shalya, with `tools_for` covering it.
2. Leela implements the group over the `apply_op` it already has, and deletes its own tool
   definitions.
3. Step-boundary steering here.
4. The trail here.

Steps 3 and 4 are independent of 1 and 2, and of each other.
