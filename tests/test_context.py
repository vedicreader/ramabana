"""The context window: what fits, what gets compacted, and what the engine says when it will not.

One functional block, gathered from three files. It was split between `test_native_errors.py`
(the window arithmetic and the fd-level capture), `test_harness.py` (compaction itself) and
`test_prefilled_thinking.py` (the filter that decides where a reply starts) -- all of it the same
subject seen from different sides.

The report behind most of it: a local Gemma refusing a turn with *"input token IDs exceed the
maximum number of tokens 4096, got 5092"*, and none of it reaching the IDE. Two faults in one
sentence. The window was believed to be 32k, so compaction never came near firing; and the
refusal happened in C++, printed to a file descriptor and returned, so no exception existed for
any `except` to catch. Both are tested without a model: the first is arithmetic, the second is a
backend that writes to fd 2 exactly the way litert does.
"""
import os
import sys
from types import SimpleNamespace

import pytest

from ramabana import core, runtime
from ramabana.core import DFLT_LOCAL_CTX, ModelSpec, local_ctx, resolve
from ramabana.runtime import (ONESHOT_TOKENS, RESERVE, Compactor, RishiBackend, ThinkFilter,
                              answer_only, captured, interesting, prefills_think, threshold)
from ramabana.runtime import capture as native_capture
from ramabana.testing import GEMMA, FakeBackend, MutteringBackend

SMALL = ModelSpec('gemma-e2b', 'litert', 'litert-community/x', 16_384)


def native_write(text):
    "Write straight to fd 2 the way a C++ engine does -- around Python's sys.stderr, not through it."
    os.write(2, text.encode())


# -- how much fits ---------------------------------------------------------------------

def test_the_window_arithmetic_holds_at_both_ends(monkeypatch):
    """The 16k reserve is larger than a 4k model's entire context, so `max(1, 4096 - 16384)` is 1
    and every conversation is instantly due -- the agent compacts two messages forever. Capping
    the reserve and the keep-tail at a fraction of the window keeps the idea (leave room for a
    reply, keep the recent turns) without inverting it, and leaves a large window alone.
    """
    assert threshold(4096) == 4096 - 1024                 # capped at a quarter
    assert threshold(200_000, 16_384) == 200_000 - 16_384  # untouched where there is room
    assert threshold(200_000) == 200_000 - RESERVE
    assert threshold(0) is None
    assert runtime.should_compact(190_000, 200_000)
    assert not runtime.should_compact(100_000, 200_000)

    c = Compactor()
    assert c.budget(4096) == 2048
    assert c.budget(200_000) == c.keep_recent

    # Under-stating a window costs one early compaction; over-stating it costs the turn.
    monkeypatch.delenv('LEELA_LOCAL_CTX', raising=False)
    assert local_ctx('gemma-e2b') == 16_384 and resolve('gemma-e2b').ctx == 16_384
    assert local_ctx('something-else') == DFLT_LOCAL_CTX
    monkeypatch.setenv('LEELA_LOCAL_CTX', '8192')
    assert local_ctx('gemma-e2b') == 8192
    monkeypatch.setenv('LEELA_LOCAL_CTX', 'gemma-e4b:16384,gemma-12b:32000')
    assert local_ctx('gemma-e4b') == 16384
    assert local_ctx('gemma-e2b') == 16_384, 'a per-model override must not move the others'


def _harness_chat(cls, hist, billed=260_915, sp='BRIEFING'):
    """A real `rishi` harness chat with no CLI behind it.

    `__new__` rather than the constructor: what is under test is the window read-out, and building
    one properly wants a Claude Code login that CI does not have.
    """
    chat = cls.__new__(cls)
    chat.hist, chat.sp, chat.toolspecs, chat._ctx_tokens = list(hist), sp, [], billed
    # `token_count` renders the prompt, which asks the chat which channel its tools are on, which
    # reads these. Without them it raises, `used_tokens` swallows that and answers with the bill
    # -- so the read-out under test here silently was not being read at all.
    chat.via, chat.mode = 'cli', ''
    return chat


def test_an_agent_harness_reports_occupancy_rather_than_what_the_turn_was_billed():
    """The window read-out these transports give, which ramabana's arithmetic takes on trust.

    Claude Code runs an internal multi-step loop and re-reads its cached prompt on every step, and
    `norm_claude_usage` folds those cache reads into `total_tokens` -- the right number for cost and
    the wrong one for the window. Measured on one real turn it over-stated a two-message
    conversation by 6.6x, and it never came back down when history was replaced, so compaction
    could not clear it and the turn refused itself with `input is too large` over a nearly empty
    context. Fixed in rishi 0.1.12, which is the floor; this is
    here so a downgrade or a regression there fails loudly rather than as a stuck agent.
    """
    from rishi.claude import ClaudeChat
    claude = ModelSpec('claude/claude-sonnet-5', 'claude', 'claude-sonnet-5', 128_000)

    hist = [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'hi'}]
    for cls, spec in ((ClaudeChat, claude),):
        b = runtime.Backend(spec)
        b.chat = _harness_chat(cls, hist)
        assert b.used_tokens < 1000, cls.__name__          # what the window holds, not the bill
        assert b.fits('one more question'), cls.__name__   # ...so the turn is not refused
        assert not runtime.should_compact(b.used_tokens, spec.ctx), cls.__name__

        # And a conversation that has genuinely filled the window is still refused.
        full = runtime.Backend(spec)
        full.chat = _harness_chat(cls, hist + [{'role': 'user', 'content': 'x' * 800_000}], billed=0)
        assert full.used_tokens > spec.ctx and not full.fits('anything'), cls.__name__

    # A hosted API bills one call per step, so its own reading is the context and is passed through.
    remote = runtime.Backend(ModelSpec('gpt', 'remote', 'gpt-5.6', 200_000))
    remote.chat = SimpleNamespace(token_count=42_000)
    assert remote.used_tokens == 42_000


# -- compaction ------------------------------------------------------------------------

def test_compaction_replaces_the_history_and_reorients_the_model(spec):
    """The checkpoint takes the place of what it summarised, and says what survived it -- which is
    the aai-coding idea, and whose value is in being specific about the kernel. The tail it keeps
    always starts at a user turn, because a tail beginning at an orphaned tool result is a dangling
    call that some providers reject outright. And a summary is updated rather than re-summarised,
    since summarising a summary loses a little every time.
    """
    be = FakeBackend(spec)
    be.start()
    be.hist_ = [{'role': 'user', 'content': 'x' * 4000}, {'role': 'assistant', 'content': 'y' * 4000},
                {'role': 'user', 'content': 'recent'}]
    out = Compactor(keep_recent=40).compact(be, lambda p, sp: 'GOAL: ship it')
    assert out == 'GOAL: ship it'
    head = be.hist[0]['content']
    assert head.startswith(runtime.SUMMARY_PREFIX) and 'GOAL: ship it' in head
    assert 'kernel process was not touched' in head and 'do not re-import' in head
    assert 'clean namespace' in runtime.reorient(kernel_alive=False)

    msgs = [{'role': 'user', 'content': 'a' * 400}, {'role': 'assistant', 'content': 'b'},
            {'role': 'tool', 'content': 'c'}, {'role': 'user', 'content': 'd'},
            {'role': 'assistant', 'content': 'e'}]
    kept = Compactor(keep_recent=50)._keep(msgs)
    assert kept and kept[0]['role'] == 'user'

    prev, rest = runtime.split_previous(
        [{'role': 'user', 'content': runtime.SUMMARY_PREFIX + 'old summary'},
         {'role': 'assistant', 'content': 'later work'}])
    assert prev == 'old summary' and len(rest) == 1
    p = runtime.summarise_prompt([{'role': 'user', 'content': runtime.SUMMARY_PREFIX + 'old summary'}])
    assert '<previous-summary>' in p and 'PRESERVE' in p


def test_compaction_progresses_under_a_briefing_that_fills_the_window():
    """Compaction fires on the whole prompt, so on a small window the conversation is only a few
    thousand tokens -- smaller than a keep-tail measured against the window, so everything was
    'recent' and `compact` returned 'nothing to compact' while the engine refused the turn.

    Subtracting the overhead is necessary and not sufficient: halving the window only progresses
    while the overhead stays under half of it, so `_keep` caps against the conversation as well.
    """
    class Briefed(Compactor):
        "Told the overhead directly, so the test does not depend on a live engine."
        def __init__(self, overhead, **kw): super().__init__(**kw); self.oh = overhead
        def overhead(self, backend, msgs, count=None): return self.oh

    be = FakeBackend(SMALL)
    be.start()
    be.hist_ = [{'role': 'user', 'content': 'a' * 14_000}, {'role': 'assistant', 'content': 'b' * 14_000},
                {'role': 'user', 'content': 'recent question'}]
    assert Briefed(5_214).compact(be, lambda p, sp: 'GOAL: keep going') == 'GOAL: keep going'
    assert be.hist[0]['content'].startswith(runtime.SUMMARY_PREFIX)

    c = Compactor()
    msgs = [{'role': 'user', 'content': 'a' * 4000}, {'role': 'assistant', 'content': 'b' * 4000},
            {'role': 'user', 'content': 'c' * 4000}, {'role': 'assistant', 'content': 'd' * 4000}]
    assert 0 < len(c._keep(msgs, ctx=16_384, overhead=9_000)) < len(msgs)   # overhead over half
    assert c.budget(200_000, 5_500) == c.keep_recent                       # large window: as before
    assert c.budget(0) == c.keep_recent                                    # no window: as before


def test_surgical_compaction_keeps_questions_calls_results_and_both_text_ends():
    "The deterministic alternative, for when there is no summariser model to pay for."
    from ramabana.runtime import surgical_history, truncate_middle
    msgs = [
        {'role': 'user', 'content': 'first ' + 'middle ' * 100 + 'last'},
        {'role': 'assistant', 'content': 'I will inspect.', 'tool_calls': [
            {'function': {'name': 'view_file', 'arguments': {'path': 'a.py'}}}]},
        {'role': 'tool', 'content': 'line one\nline two'},
    ]
    text = surgical_history(msgs, {'user': 20, 'assistant': 20, 'call': 30, 'result': 20})
    assert text.startswith('§ first ') and 'last §' in text
    assert "▶ view_file(path='a.py')" in text
    assert '> line one ¶ line two' in text
    clipped = truncate_middle('begin ' + 'x ' * 200 + 'end', 12)
    assert clipped.startswith('begin ') and clipped.endswith('end')


# -- what the engine says on its way past ----------------------------------------------

def test_the_engines_own_words_are_captured_and_classified():
    """Captured for the IDE and teed to where they were going, because a terminal session still
    wants them. A line saying "exceed" is a problem; a line announcing an XNNPACK delegate is
    chatter, and an engine that logs one per call would otherwise bury the line that matters.
    A native layer also repeats itself once per token, and a status bar cannot.
    """
    with captured() as cap: native_write(GEMMA)
    assert 'exceed the maximum number of tokens 4096' in cap.text
    assert cap.problems, 'a line saying "exceed" is a problem, not chatter'

    with captured() as cap: native_write('INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\n')
    assert cap.text and not cap.problems

    assert interesting(GEMMA * 5) == [GEMMA.strip()]
    assert len(interesting('\n'.join(f'error {i}' for i in range(20)))) == 4

    # An exception carries them, so the reported failure is the engine's words not a wrapper's.
    def boom():
        native_write(GEMMA)
        raise RuntimeError('generate failed')
    with pytest.raises(RuntimeError) as e: native_capture(boom)
    assert 'exceed the maximum number of tokens' in getattr(e.value, 'native_output', '')


def test_capture_can_be_switched_off_and_never_breaks_the_descriptor(monkeypatch):
    """Anything that moves a file descriptor needs a way out, and `use_env_prefix` exists so one
    hard-coded variable name is not wrong in every other application. A broken stderr would be a
    far worse bug than the one this fixes, so the descriptor survives an exception inside the block.
    """
    monkeypatch.setenv('LEELA_NO_NATIVE_CAPTURE', '1')
    with captured() as cap: native_write('x\n')
    assert cap.text == ''
    monkeypatch.delenv('LEELA_NO_NATIVE_CAPTURE')

    core.use_env_prefix('RAMABANA_', 'LEELA_')
    monkeypatch.setenv('RAMABANA_NO_NATIVE_CAPTURE', '1')
    assert captured().enabled is False
    monkeypatch.delenv('RAMABANA_NO_NATIVE_CAPTURE')
    assert captured().enabled is True

    before = os.dup(2)
    try:
        with pytest.raises(ValueError):
            with captured():
                native_write('something\n')
                raise ValueError('boom')
        native_write('')                       # fd 2 is still writable
        assert sys.stderr is not None
    finally: os.close(before)


def test_a_silent_engine_failure_is_reported_rather_than_shown_as_an_empty_answer():
    """The bug as the user met it: a turn that produced nothing and said nothing about it. A stream
    with no chunks ended with a blank pane and a cheerful status line. `oneshot` still returns ''
    by contract -- completion, classification and compaction all need a value, not an exception --
    so its failure has to be recorded somewhere the user can see instead.
    """
    be = MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))
    out = ''.join(be.stream('hello'))
    assert 'exceed the maximum number of tokens 4096' in out and be.problems

    cheap = MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))
    assert cheap.oneshot('summarise this') == ''
    assert any('input too long' in p for p in cheap.problems)


# -- where a reply starts --------------------------------------------------------------

def test_a_template_that_opens_a_think_block_is_detected():
    """Rishi's splitter waits for a `<think>` to know it is inside a thought, so for a model whose
    template opens one, the deliberation arrives as ordinary reply text and only the closing tag
    comes back. Detection must never raise: a backend that never started has no tokenizer."""
    class Tok:
        def __init__(self, tail): self.tail = tail
        def apply_chat_template(self, msgs, **kw): return '<|im_start|>assistant\n' + self.tail

    class Chat:
        def __init__(self, tail): self.tokenizer = Tok(tail)

    assert prefills_think(Chat('<think>\n')) is True
    assert prefills_think(Chat('<think>\n\n</think>\n\n')) is False   # enable_thinking=False
    assert prefills_think(Chat('')) is False                          # not a reasoning model

    class Boom:
        def apply_chat_template(self, *a, **kw): raise RuntimeError('no template')
    bad = Chat('')
    bad.tokenizer = Boom()
    assert prefills_think(bad) is False
    assert prefills_think(None) is False                              # never started


def test_the_think_filter_strips_deliberation_and_re_arms_each_step():
    """The template opens a fresh thought per step, so one strip per turn is not enough. A thought
    that never reaches an answer is visible to the caller rather than silently empty, and the
    blocking path must not disagree with the streamed one about where the reply starts."""
    def chunks(*texts): return [{'content': [{'type': 'text', 'text': t}]} for t in texts]
    def text_of(cs): return ''.join(p.get('text', '') for c in cs
                                    for p in (c.get('content') or []) if p.get('type') == 'text')

    f = ThinkFilter()
    assert text_of(list(f(chunks('Six sevens', ' are 42.\n</th', 'ink>\n\n', '42')))) == '42'
    assert (f.thought, f.answer) == (29, 2)          # `thought` counts the buffered tag too

    tool = {'content': [{'type': 'tool_call', 'name': 'search_code', 'arguments': {}}]}
    out = list(ThinkFilter()(chunks('think 1', '</think>', 'calling ') + [tool]
                             + chunks('think 2', '</think>', 'done')))
    assert text_of(out) == 'calling done'
    assert out[1] is tool                            # the call itself passes through untouched

    g = ThinkFilter()
    assert text_of(list(g(chunks('deliberating', '</think>\n\n')))) == ''
    assert (g.thinking, g.answer) == (False, 0)      # what `_stream` reports as a problem
    h = ThinkFilter()
    assert text_of(list(h(chunks('cut off at the cap')))) == ''
    assert (h.thinking, h.answer) == (True, 0)

    for raw in ('thinking\n</think>\n\n42', '<think>thinking</think>42'):
        assert answer_only(raw) == '42'
    assert text_of(list(ThinkFilter()(chunks('thinking\n</think>\n\n42')))) == '42'


def test_a_cheap_job_cannot_leave_its_output_cap_behind():
    """`_oneshot_chat` is reused across jobs, so a 32-token `classify` must not cap the next
    summary at 32 tokens as well."""
    caps = []

    class Chat:
        def __init__(self): self.sp, self.hist = '', []
        def mk_msg(self, p): return {'role': 'user', 'content': p}
        def _model_step(self, mx): caps.append(mx); return {'content': 'ok'}

    class Local(RishiBackend):
        def _start(self): return Chat()

    b = Local(ModelSpec('test-mlx', 'mlx', 'test/model', 8192))
    b._oneshot_chat = Chat()
    b.start()
    b.oneshot('label this', 'pick one', 32)
    b.oneshot('summarise this')
    assert caps == [32, ONESHOT_TOKENS]


def test_a_summariser_that_overflows_is_retried_on_half_the_budget(spec):
    """A prompt built to fill the summary model's window can still overflow it, because for any
    backend without a tokenizer of its own the budget was only estimated. Measured against ollama,
    chars/4 ran 12% under what ornith and qwen3 actually tokenise, so compaction of a conversation
    already well past its window died on a 400 and left the history untouched -- the one moment
    compaction exists for. Halving the budget and asking again costs a shorter summary, which is
    always better than no summary.
    """
    be = FakeBackend(spec)
    be.start()
    be.hist_ = [{'role': 'user', 'content': 'x' * 40000}, {'role': 'assistant', 'content': 'y' * 40000},
                {'role': 'user', 'content': 'recent'}]
    seen = []

    def picky(prompt, sp):
        seen.append(len(prompt))
        if len(seen) < 3: raise RuntimeError('exceeds the available context size')
        return 'GOAL: ship it'

    out = Compactor(keep_recent=40).compact(be, picky, summary_ctx=2048, summary_count=None)
    assert out == 'GOAL: ship it', 'the third, smallest prompt should have been accepted'
    assert len(seen) == 3 and seen[0] > seen[1] > seen[2], f'budget did not halve: {seen}'
    assert runtime.SUMMARY_PREFIX in be.hist[0]['content']

    # every attempt failing still reports the transport's own words, not a bare 'returned nothing'
    c = Compactor(keep_recent=40)
    be2 = FakeBackend(spec); be2.start(); be2.hist_ = list(be.hist_)
    assert c.compact(be2, lambda p, sp: (_ for _ in ()).throw(RuntimeError('boom')),
                     summary_ctx=2048, summary_count=None) == ''
    assert 'boom' in c.note and be2.hist == be2.hist_


def test_the_token_estimate_errs_high_so_a_prompt_built_to_fit_does(spec):
    """Estimating low overflows the window and costs the whole compaction; estimating high costs a
    slightly shorter prompt. ornith-1.5:9b and qwen3:0.6b both tokenise English prose at 3.50
    chars/token, so the estimator must stay at or under that.
    """
    assert runtime.CHARS_PER_TOKEN <= 3.5
    assert runtime.estimate_tokens('x' * 126438) >= 36110, 'measured on ornith for this length'
    assert runtime.estimate_tokens('') == 0 and runtime.estimate_tokens('a') == 1
    assert isinstance(runtime.estimate_tokens('x' * 999), int)
    assert runtime.halvings(31614) == [31614, 15807, 7903]
    assert runtime.halvings(None) == [None] and runtime.halvings(0) == [0]
    # a tokenizer that is present is still believed over the estimate
    assert runtime.estimate_tokens('x' * 1000, count=lambda t: 7) == 7
