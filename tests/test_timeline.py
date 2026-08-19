"""The transcript as a timeline: what order a turn's blocks land in, and what folds.

Teleprint orders blocks by creation and lets only the newest grow, so growing one block across a
whole turn put every word of narration above every call the turn made -- the narration in one place,
the calls in another, and the answer at the bottom of the narration rather than at the bottom of the
screen. These tests pin the order, the disclosure, and the one repaint contract that makes streaming
affordable: a block's model text is current on every chunk however rarely it re-renders.

Nothing here loads a model, and nothing here touches a real terminal.
"""
import asyncio, time

import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.cli import ACT_TAIL, FOLD_STEP, GUTTERS, Ui
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


def test_a_tool_call_lands_below_the_prose_that_introduced_it(ui):
    blocks = a_turn(ui, [('Looking for it.\n', 'search_code', 'runtime.py:88'),
                         ('And the caller.\n', 'view_file', 'line 120'),
                         ('And the tests.\n', 'search_code', 'test_context.py:44')])
    assert [b.tag for b in blocks] == ['step', 'tool', 'step', 'tool', 'step', 'tool', 'reply']


def test_only_the_segment_no_call_ended_stays_a_reply(ui):
    "Which segment is the answer is decided by what never happened to it, so `/copy` can find it."
    blocks = a_turn(ui, [('Looking.\n', 'search_code', 'hit')])
    assert [b.tag for b in blocks] == ['step', 'tool', 'reply']
    answer = blocks[-1]
    assert ui.transcript.block_text(answer) == '## Answer\n\nBoth of them.\n'
    assert 'copied' in ui.copy_last('reply')
    assert blocks[0].gutter is GUTTERS['step'] and blocks[0].collapse_at == FOLD_STEP


def test_a_narration_step_folds_to_one_row_and_the_answer_does_not(ui):
    long = 'Let me work through this.\n' + ''.join(f'thought {i}\n' for i in range(30))
    blocks = a_turn(ui, [(long, 'search_code', 'hit\n' * 40)])
    step, tool, answer = blocks
    assert step.height > FOLD_STEP and step.collapsed
    assert len(ui.comp._block_rows(step)) == 1
    assert tool.collapsed and len(ui.comp._block_rows(tool)) == 1
    assert not answer.collapsed, 'the answer must never be born folded'


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


def test_the_whole_turn_is_reset_per_turn_not_per_segment(ui):
    "`stream` used to reset on a missing block, which after splitting is every segment's first chunk."
    a_turn(ui, [('one.\n', 'search_code', 'x'), ('two.\n', 'search_code', 'y')], answer='three.\n')
    assert ui._reply == 'one.\ntwo.\nthree.\n', ui._reply
    assert ui._seg == 'three.\n', 'the open segment is the answer alone'


def test_ctrl_o_reaches_every_step_and_call_of_the_turn(ui):
    "It used to reach the newest block, which after a long turn is the least interesting one."
    # two paragraphs, so the step renders taller than one row and therefore has something to fold
    blocks = a_turn(ui, [(f'step {i}.\n\nmore.\n', 'search_code', 'hit\n' * 5) for i in range(6)])
    work = [b for b in blocks if b.tag in ('step', 'tool') and b.height > 1]
    assert len(work) == 12 and all(b.collapsed for b in work), 'the resting timeline is one row per entry'

    assert ui.fold_work() is False and not any(b.collapsed for b in work)
    assert ui.fold_work() is True and all(b.collapsed for b in work)

    work[0].collapsed = False           # part-open, as drilling in from the transcript leaves it
    assert ui.fold_work() is True and all(b.collapsed for b in work)
    assert not blocks[-1].collapsed, 'the answer is not part of the working'


def test_the_working_footer_says_where_the_model_is_at_only_while_a_turn_runs(ui):
    blocks = a_turn(ui, [(f'step {i}.\n', 'search_code', 'hit') for i in range(5)])
    assert ui.working() == [], 'at rest the footer is not there at all'

    ui._turn_at, ui.turn = time.monotonic(), 'a turn'
    rows = [r.plain for r in ui.working()]
    assert len(rows) == ACT_TAIL + 1, rows
    recent = [a.line() for a in ui.agent.activity.since()][-ACT_TAIL:]
    assert [r.split(' ', 1)[1].strip() for r in rows[:-1]] == recent
    assert rows[-1].startswith('  step 5 ·'), rows[-1]

    ui.turn = None
    assert ui.working() == []
    assert all(b.tag != 'note' for b in blocks[-1:]), 'the footer must not print blocks'


def test_the_footer_is_tail_and_sits_directly_above_the_prompt(ui):
    "It never inks, so it leaves nothing in the transcript to scroll past once the turn is over."
    a_turn(ui, [('looking.\n', 'search_code', 'hit')])
    before = len(ui.comp.blocks)
    ui._turn_at, ui.turn = time.monotonic(), 'a turn'
    rows, cursor = ui.tail()
    assert len(ui.comp.blocks) == before, 'the footer printed a block'
    assert cursor[0] == len(rows) - 1, 'the cursor is on the prompt, which is the last row'
    assert rows[-2].plain.startswith('  step 1 ·'), [r.plain for r in rows]


def test_the_footer_numbers_what_alt_digit_reaches(ui):
    """The drill-in and the footer must agree, or the number in front of a call points at another
    one. Teleprint's own alt-digit numbering wants a three-glyph gutter, which these are not.
    """
    a_turn(ui, [(f'step {i}.\n', 'search_code', 'hit\n' * 4) for i in range(4)])
    ui._turn_at, ui.turn = time.monotonic(), 'a turn'

    newest = ui.drillable()
    assert newest and all(b.collapsed for b in newest)
    rows = [r.plain for r in ui.working()][:-1]
    assert [r.split(' ', 1)[0] for r in rows] == ['3', '2', '1'], rows

    assert ui.drill(1) is True and not newest[0].collapsed, 'alt+1 missed the newest entry'
    assert ui.drill(1) is True and newest[0].collapsed
    assert ui.drill(len(newest)) is True and not newest[-1].collapsed
    assert ui.drill(len(newest) + 1) is False, 'a digit past the end must do nothing'


def test_a_delegate_holds_its_sub_agents_calls_instead_of_scattering_them(ui):
    """Sub-agent calls used to land as siblings of the caller's own with nothing saying whose they
    were, which is most of why a delegating turn read as the same search over and over.
    """
    acts = ui.agent.activity
    parent = acts.start('delegate_search', {'question': 'which files import fastllm?'})
    kids = [acts.start('search_code', {'query': q}, parent_action_id=parent.id)
            for q in ('fastllm', 'import fastllm')]
    for k in kids: acts.finish(k, 'a hit')
    acts.finish(parent, 'Three files do.')

    blocks = list(ui.comp.blocks.values())
    assert len(blocks) == 1, [b.tag for b in blocks]      # one block, not three
    group = blocks[0]
    assert group.collapsed and len(ui.comp._block_rows(group)) == 1
    text = ui.transcript.block_text(group)
    assert 'which files import fastllm?' in text
    assert all(k.line() in text for k in kids), text
    assert 'Three files do.' in text
    assert '2 calls' in ui.comp._ansi(ui.comp._block_rows(group)[0][1])


def test_a_failed_call_never_folds_and_a_running_one_is_not_painted_as_done(ui):
    "An error you have to expand is the one thing on the surface nobody wants hidden."
    acts = ui.agent.activity
    bad = acts.start('run_shell', {'command': 'make'})
    running = ui.comp._ansi(ui.comp._block_rows(ui.acts[bad.id])[0][1])
    assert GUTTERS['tool'][0].plain in running

    acts.finish(bad, 'error: no rule to make target\n' * 10, ok=False)
    blk = ui.acts[bad.id]
    assert blk.height > 1 and not blk.collapsed, 'a failure folded itself away'

    good = acts.start('run_shell', {'command': 'ls'})
    acts.finish(good, 'a\nb\nc\nd\n')
    assert ui.acts[good.id].collapsed, 'a success should fold to its summary'


def test_copy_turn_yields_every_word_the_turn_said(ui):
    "Since a turn became a timeline, no single block holds all of its prose."
    a_turn(ui, [('looking.\n', 'search_code', 'hit'), ('and again.\n', 'search_code', 'hit')],
           answer='done.\n')
    assert 'copied' in ui.copy_last('turn')
    assert ui._reply == 'looking.\nand again.\ndone.\n'
    assert ui.copy_last('turn').startswith(f'copied {len(ui._reply)} chars')


def test_the_bindings_arrive_through_the_real_key_parser(ui):
    "Bound behaviour is only bound if the bytes a terminal actually sends reach it."
    ui.comp.on_key = ui.on_key
    a_turn(ui, [('looking.\n\nand looking.\n', 'search_code', 'hit\n' * 5)], answer='done.\n')
    ui._seg_blk = None
    entries = ui.drillable()
    assert [b.tag for b in entries] == ['tool', 'step'] and all(b.collapsed for b in entries)

    ui.comp.on_bytes(b'\x1b1')                     # alt+1
    assert not entries[0].collapsed, 'alt+1 missed the newest entry'
    ui.comp.on_bytes(b'\x1b2')
    assert not entries[1].collapsed
    ui.comp.on_bytes(b'\x1b1')
    ui.comp.on_bytes(b'\x1b2')
    assert all(b.collapsed for b in entries), 'pressing again did not shut them'
    assert ui.buf.text == '', f'alt+digit leaked into the composer: {ui.buf.text!r}'

    ui.comp.on_bytes(b'\x1b0')                     # alt+0 is not a binding, and must not type either
    assert ui.buf.text == '' and all(b.collapsed for b in entries)

    ui.comp.on_bytes(b'\x0f')                      # ctrl+o
    assert not any(b.collapsed for b in entries), 'ctrl+o did not open the working'


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
    every = [b for b in ui.comp.blocks.values() if b.tag in ('step', 'tool') and b.height > 1]
    assert len(every) == 12, len(every)

    assert len(ui.turn_blocks()) < len(ui.comp.blocks), 'the turn is not a subset of the session'
    assert len(ui.drillable()) == 4, [b.tag for b in ui.drillable()]

    ui.fold_work()
    opened = [b for b in every if not b.collapsed]
    assert len(opened) == 4, f'ctrl+o opened {len(opened)} blocks across earlier turns'
    assert all(b in ui.turn_blocks() for b in opened)


def test_copy_says_no_reply_rather_than_reaching_back_a_turn(ui):
    "A turn that ends on a tool call leaves no `reply` block; the answer above it is a different turn's."
    a_finished_turn(ui, answer='THE ANSWER OF TURN ONE\n')
    assert 'copied 23 chars' in ui.copy_last('reply')

    ui.say('another question', 'user', pad=True)
    ui._reply, ui._seg, ui._seg_blk, ui._rendered = '', '', None, ''
    ui._turn_from = next(reversed(ui.comp.blocks), 0)
    seg = ui.stream(None, 'looking.\n')
    act = ui.agent.activity.start('view_file', {'path': 'a.py'})
    ui.agent.activity.finish(act, 'contents')     # ...and the turn stops here, with no prose after
    ui.flush_stream(); ui._seg_blk = None

    assert 'reply' not in [b.tag for b in ui.turn_blocks()]
    assert ui.copy_last('reply') == 'no reply block in this turn to copy'


def test_a_running_delegate_shows_a_bounded_window_of_its_sub_calls(ui):
    """It stays open while it runs so the sub-agent's work is watchable, and a block that is both
    newest and growing pushes rows across the top edge, where they ink. Sixty calls would leave
    forty inked rows of exactly the scattering the grouping exists to prevent.
    """
    from ramabana.cli import MAX_GROUP_ROWS
    acts = ui.agent.activity
    parent = acts.start('delegate_parallel', {'questions': '["a","b"]'})
    kids = [acts.start('search_code', {'query': str(i)}, parent_action_id=parent.id) for i in range(60)]
    for k in kids: acts.finish(k, 'a hit')

    group = ui.acts[parent.id]
    assert not group.collapsed, 'it should be open while it runs'
    assert group.height <= MAX_GROUP_ROWS + 2, f'{group.height} rows on screen for 60 calls'
    drawn = '\n'.join(''.join(s.text for s in l) for l in ui.comp._content_lines(group))
    assert '… 52 earlier' in drawn, drawn
    assert all(k.line() in ui.transcript.block_text(group) for k in kids), 'source lost calls'

    acts.finish(parent, 'answered')
    assert group.collapsed and len(ui.comp._block_rows(group)) == 1


def test_the_footer_survives_a_session_longer_than_the_activity_window(ui):
    "`Activity` slid its window without sliding the turn mark, so `since()` went empty forever."
    acts = ui.agent.activity
    for i in range(acts.max_acts + 5): acts.finish(acts.start('search_code', {'query': str(i)}), 'x')
    acts.mark('a later turn')
    acts.finish(acts.start('view_file', {'path': 'a.py'}), 'contents')

    assert [a.tool for a in acts.since()] == ['view_file'], acts.since()
    ui.turn, ui._turn_at = 'a turn', time.monotonic()
    assert [r.plain for r in ui.working()][-1].startswith('  step 1 ·')


def test_an_act_whose_parent_has_no_block_is_counted_as_its_own(ui):
    "A replayed session, or an overridden `_action_meta`, can name a parent this surface never saw."
    ui.turn, ui._turn_at = 'a turn', time.monotonic()
    ui.agent.activity.start('search_code', {'query': 'x'}, parent_action_id='deadbeef')
    orphan = ui.agent.activity.acts[-1]
    rows = [r.plain for r in ui.working()]
    assert rows[-1].startswith('  step 1 ·'), rows        # counted, not written off as delegated
    assert 'delegated' not in rows[-1], rows[-1]
    assert rows[0] == f'  {orphan.line()}', rows          # and not indented as somebody's child

    ui.agent.activity.finish(orphan, 'a hit\n' * 6)      # once it has something to fold, it numbers
    assert [r.plain for r in ui.working()][0].startswith('1 ')


def test_a_second_turn_cannot_start_over_a_running_one(ui):
    "The two share `_reply` and the segment state, so the newcomer's reset wiped the first's words."
    async def noop(): pass
    ui.turn = 'a turn in flight'
    coro = noop()
    assert ui.start_turn(coro) is False
    assert ui.turn == 'a turn in flight', 'the running turn was replaced'
    assert [b.tag for b in ui.comp.blocks.values()][-1] == 'note'


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
