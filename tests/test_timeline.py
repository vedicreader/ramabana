"""The transcript as a timeline: what order a turn's blocks land in, and what folds.

Teleprint orders blocks by creation and lets only the newest grow, so growing one block across a
whole turn put every word of narration above every call the turn made -- the narration in one place,
the calls in another, and the answer at the bottom of the narration rather than at the bottom of the
screen. These tests pin the order, the disclosure, and the one repaint contract that makes streaming
affordable: a block's model text is current on every chunk however rarely it re-renders.

Nothing here loads a model, and nothing here touches a real terminal.
"""
import asyncio

import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import FOLD_STEP, Ui
from ramabana.testing import fake_agent


@pytest.fixture
def ui():
    "A whole CLI surface over an emulated terminal, with no loop registered so every call is direct."
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None   # a worker thread has no signals to take
    asyncio.run(comp.start())               # one CPR round trip, which the emulator answers
    agent, _ = fake_agent()
    yield Ui(comp, agent)
    tty.close()


def a_turn(u, steps, answer='## Answer\n\nBoth of them.\n'):
    "Drive `steps` of (narration, tool, result) through the real streaming and activity paths."
    acts, seg = u.agent.activity, None
    for prose, tool, out in steps:
        seg = u.stream(seg, prose)
        act = acts.start(tool, {'query': 'threshold'})
        acts.finish(act, out)
    seg = u.stream(seg, answer)
    u.flush_stream()
    return list(u.comp.blocks.values())


def test_narration_stays_as_a_step_above_each_call(ui):
    blocks = a_turn(ui, [('Looking for it.\n', 'search_code', 'runtime.py:88'),
                         ('And the caller.\n', 'view_file', 'line 120'),
                         ('And the tests.\n', 'search_code', 'test_context.py:44')])
    assert [b.tag for b in blocks] == ['step', 'tool', 'step', 'tool', 'step', 'tool', 'reply']
    assert [ui.transcript.block_text(b) for b in blocks if b.tag == 'step'] == ['Looking for it.', 'And the caller.', 'And the tests.']
    assert all(not b.collapsed for b in blocks if b.tag == 'step'), 'narration is there to be read'
    assert ui.transcript.block_text(blocks[-1]) == '## Answer\n\nBoth of them.\n'
    assert ui._reply == '## Answer\n\nBoth of them.\n'


def test_a_growing_segment_keeps_its_model_text_current_between_repaints(ui):
    """The repaint throttle is what makes a long reply affordable -- re-rendering the whole
    accumulated Markdown per chunk costs time quadratic in its length -- but search and copy read
    the model, so the model may never lag the stream by even one chunk.
    """
    md = 'Here is the fix.\n\n```python\nthreshold = 42\n```\n\nCall it from `runtime.py`.'
    seg = None
    for i, ch in enumerate(md):         # one character at a time: the throttle skips nearly all of them
        seg = ui.stream(seg, ch)
        assert ui.transcript.block_text(seg) == md[:i + 1], f'the model lagged at char {i}'
    ui.flush_stream()
    rendered = '\n'.join(''.join(s.text for s in l) for l in ui.comp._content_lines(seg))
    assert '```' not in rendered, 'the fence should be rendered, not printed'
    assert '```python' in ui.transcript.block_text(seg), 'copy must yield paste-able Markdown'


def test_stopping_a_turn_does_not_leave_the_reply_growing_above_the_note(ui):
    """Ctrl-C prints `stopping` as a block. With the segment still open, the next chunk to arrive
    grew a block that was no longer the newest, so late text appeared above the note.
    """
    ui.turn = 'a turn'
    seg = ui.stream(None, 'part way through')
    ui.on_key(Key('ctrl+c'))

    assert ui._seg_blk is None
    assert ui.transcript.block_text(seg) == 'part way through', 'the flush lost the last chunk'
    tags = [b.tag for b in ui.comp.blocks.values()]
    assert tags == ['reply', 'note'], tags

    ui.stream(seg, ' and a straggler')
    tags = [b.tag for b in ui.comp.blocks.values()]
    assert tags == ['reply', 'note', 'reply'], 'the straggler grew the block above the note'


# -- what a review found: six ways the surface reached outside the turn it was showing -------------

def a_finished_turn(u, n_calls=2, answer='done.\n'):
    "Run a turn the way `run_turn` does, including the bookkeeping that scopes the turn."
    u.say('a question', 'user', pad=True)
    u._reply, u._seg, u._seg_blk, u._rendered = '', '', None, ''
    u._turn_from = next(reversed(u.comp.blocks), 0)
    u.agent.activity.mark()
    a_turn(u, [(f'step {i}.\n\nmore.\n', 'search_code', 'hit\n' * 8) for i in range(n_calls)], answer)
    u._seg_blk = None


def test_folding_and_drilling_reach_this_turn_and_not_the_session(ui):
    """Teleprint commits blocks only on a borrow, so `not committed` is the whole session. Ctrl-O
    over twenty turns of tool results pushes thousands of rows past the top edge, and everything
    that crosses it is inked into scrollback for good -- no keystroke takes it back.
    """
    for _ in range(3): a_finished_turn(ui)
    every = [b for b in ui.comp.blocks.values() if b.tag == 'tool' and b.height > 1]
    assert len(every) == 6, len(every)

    assert len(ui.turn_blocks()) < len(ui.comp.blocks), 'the turn is not a subset of the session'
    assert len(ui.drillable()) == 2, [b.tag for b in ui.drillable()]

    ui.fold_work()
    opened = [b for b in every if not b.collapsed]
    assert len(opened) == 2, f'ctrl+o opened {len(opened)} blocks across earlier turns'
    assert all(b in ui.turn_blocks() for b in opened)


def test_a_model_that_stalls_mid_prose_does_not_leave_its_last_words_unseen():
    """Every *boundary* flushes, but a stall is not a boundary: the chunk before a long pause stayed
    undrawn for the whole pause. `animate` flushes on its frame, and skips when there is nothing new.
    """
    async def go():
        tty = EmuTty(80, 12)
        comp = Compositor(tty)
        comp._register_signals = lambda: None
        await comp.start()
        agent, _ = fake_agent()
        u = Ui(comp, agent)
        u.turn = 'a turn'
        spinner = comp.spawn(u.animate(), name='spinner')
        try:
            seg = u.stream(None, 'first chunk. ')
            seg = u.stream(seg, 'SECOND CHUNK')   # inside STREAM_EVERY, so not drawn yet
            drawn = lambda: '\n'.join(''.join(s.text for s in l)
                                      for l in comp._content_lines(seg))
            assert 'SECOND CHUNK' not in drawn(), 'the throttle did not throttle'
            await asyncio.sleep(0.3)
            assert 'SECOND CHUNK' in drawn(), 'the stalled tail is still invisible'

            n = [0]
            real = comp.set_body
            comp.set_body = lambda *a, **k: (n.__setitem__(0, n[0] + 1), real(*a, **k))[1]
            await asyncio.sleep(0.4)              # nothing new arrives
            assert n[0] == 0, f'the timer re-rendered {n[0]} times with nothing to draw'
        finally:
            spinner.cancel()
            tty.close()
    asyncio.run(go())

def _banner_copies(comp, tty, calls):
    "How many times the first block reaches the terminal while `calls` tool results fold under it."
    from rich.text import Text
    wrote, real = [], tty.write
    tty.write = lambda s: (wrote.append(s), real(s))[1]
    comp.print_block(Text('BANNER'), tag='note', collapse_at=None, source='BANNER')
    for n in range(calls):
        blk = comp.print_block(Text('\n'.join(f'{n} line {i}' for i in range(30))),
                               tag='tool', collapse_at=None, source='x')
        comp._frame()
        blk.collapsed, blk.collapse_at = True, 1      # the fold `_act` applies when a result lands
        comp._dirty(blk); comp._frame()
    return ''.join(wrote).count('BANNER'), comp._ws


def test_a_folded_call_does_not_ink_the_transcript_above_it_again():
    """Teleprint's `_frame` ended by assigning the scrolled-off row count, which lowered it whenever
    the document shrank -- and a tool result folding to one row is a large shrink. The rows above
    were then inked a second time on the next growth, so a turn of twenty-three folded calls left
    twenty-three copies of the startup banner in the scrollback. `cli` patches the mark to rise
    only; rows the terminal already has cannot be taken back."""
    from ramabana.cli import INK_PATCHED
    from teleprint.compositor import Compositor
    assert INK_PATCHED, 'teleprint fixed it: drop the patch and this test with it'
    marks = []
    for frame in (Compositor._frame, Compositor._frame.__wrapped__):
        tty = EmuTty(40, 8)
        comp = Compositor(tty); comp._register_signals = lambda: None
        asyncio.run(comp.start())
        comp._frame = frame.__get__(comp)
        marks.append(_banner_copies(comp, tty, 8))
        tty.close()
    (patched, mark), (bare, _) = marks
    assert mark > 0, 'the document has to outgrow the window for anything to be inked at all'
    assert patched < bare, f'patched inked the banner {patched} times, unpatched {bare}'


def test_a_turn_that_ends_during_a_poll_still_shows_its_answer(monkeypatch):
    """The Claude tags channel hands over a step's whole text in one chunk, just before the run
    finishes. A poll that timed out in that same tick saw `terminal` and left the chunk in the
    queue, so the whole answer was lost from the screen though the history had it."""
    from ramabana.agent import Agent
    from ramabana.cli import run_turn
    from ramabana.testing import MemHost, ScriptedBackend, Step
    real, first = asyncio.wait_for, [True]
    async def late_poll(aw, timeout):
        if not first[0]: return await real(aw, timeout)
        first[0] = False
        await asyncio.sleep(.3)   # the loop is busy while the turn finishes
        aw.close()
        raise asyncio.TimeoutError
    async def go():
        tty = EmuTty(80, 24)
        comp = Compositor(tty); comp._register_signals = lambda: None
        await comp.start()
        a = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), extensions=False, subagents=False, profile='full')
        be = ScriptedBackend(steps=[Step('THE WHOLE ANSWER')], token_delay=0, tools=a.tools)
        a.routing.spec = lambda job='turn', fallback=True: be.spec
        a._be = a._be_or_none = lambda job='turn': be
        u = Ui(comp, a, loop=asyncio.get_running_loop())
        monkeypatch.setattr(asyncio, 'wait_for', late_poll)
        await run_turn(u, 'a question')
        tty.close()
        return u
    u = asyncio.run(go())
    assert u._reply.strip() == 'THE WHOLE ANSWER', repr(u._reply)
    assert any(b.tag == 'reply' and u.transcript.block_text(b).strip() == 'THE WHOLE ANSWER' for b in u.comp.blocks.values())
