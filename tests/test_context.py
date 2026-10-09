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
from types import SimpleNamespace

from ramabana import runtime
from ramabana.core import DFLT_LOCAL_CTX, ModelSpec, local_ctx, resolve
from ramabana.runtime import RESERVE, Compactor, captured, threshold
from ramabana.testing import FakeBackend

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
    from urai import ChatOpts
    chat = cls.__new__(cls)
    # `sp` is a property over `opts` in urai, so an uninitialised chat has to be given one
    chat.opts = ChatOpts.create(None, sp=sp)
    # `token_count` renders the prompt, which asks the chat which channel its tools are on, which
    # reads `opts.tool_mode`. Without it that raises, `used_tokens` swallows it and answers with
    # the bill -- so the read-out under test here silently was not being read at all.
    chat.hist, chat.toolspecs, chat._ctx_tokens = list(hist), [], billed
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


# -- what the engine says on its way past ----------------------------------------------

def test_a_capture_longer_than_one_pipe_read_keeps_its_tail():
    """`stop` closed the pipe's read end before joining the thread that drains it, so whatever was
    still in the pipe went with it: a 60k write came back as its first 4096-byte chunk, and under
    load a short one came back empty. Restoring the descriptor is what ends the pump, so the join
    belongs between that and the close.
    """
    with captured() as cap: native_write('a' * 59_990 + 'THE-TAIL\n')
    assert cap.text.endswith('THE-TAIL\n')
    assert len(cap.text) == runtime.MAX_KEEP, 'the tail is kept, not the first read'
