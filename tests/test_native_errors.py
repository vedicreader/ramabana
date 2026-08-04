"""Tests for failures that never raised, and for the window that made them happen.

The report these come from: a local Gemma refusing a turn with *"input token IDs exceed
the maximum number of tokens 4096, got 5092"*, and none of it reaching the IDE. Two
separate faults behind that one sentence:

- leela believed the model's window was 32k, so compaction never came near firing and the
  conversation was allowed to grow until the engine refused it;
- the refusal happened in C++, printed to a file descriptor, and returned -- so no
  exception existed for any `except` in the harness to catch, and the frontends had
  nothing to show.

Both are tested here without a model: the first is arithmetic, and the second is a fake
backend that writes to fd 2 exactly the way litert does.
"""

import os
import sys

import pytest

from ramabana.backend import Backend, Usage
from ramabana.compact import Compactor, RESERVE, threshold
from ramabana.models import DFLT_LOCAL_CTX, local_ctx, resolve
from ramabana.native import captured, interesting
from ramabana.native import capture as native_capture
from ramabana.testing import GEMMA, MutteringBackend


# ---- the window ------------------------------------------------------------
def test_a_small_window_is_not_swamped_by_the_reserve():
    """The 16k reserve is bigger than a 4k local model's entire context.

    `max(1, 4096 - 16384)` is 1, so every conversation is instantly "due" and the agent
    compacts two messages, forever. Capping the reserve at a quarter of the window keeps
    the idea (leave room for a reply) without inverting it.
    """
    assert threshold(4096) == 4096 - 1024
    assert threshold(200_000) == 200_000 - RESERVE      # unchanged where there is room
    assert threshold(0) is None


def test_recent_is_capped_by_the_window_too():
    """20k of "recent" on a 4k model means nothing is ever old enough to summarise.

    This is the other half of the same failure: with the whole conversation inside the
    keep-recent budget, `compact()` reports "everything is recent; nothing to compact" and
    returns -- right up to the point where the engine refuses the turn.
    """
    c = Compactor()
    assert c.budget(4096) == 2048
    assert c.budget(200_000) == c.keep_recent


def test_the_local_window_errs_small_and_can_be_overridden(monkeypatch):
    "Under-stating a window costs one early compaction; over-stating it costs the turn."
    monkeypatch.delenv('LEELA_LOCAL_CTX', raising=False)
    assert local_ctx('gemma-e2b') == 4096
    assert resolve('gemma-e2b').ctx == 4096
    assert local_ctx('something-else') == DFLT_LOCAL_CTX
    monkeypatch.setenv('LEELA_LOCAL_CTX', '8192')
    assert local_ctx('gemma-e2b') == 8192
    monkeypatch.setenv('LEELA_LOCAL_CTX', 'gemma-e4b:16384,gemma-12b:32000')
    assert local_ctx('gemma-e4b') == 16384
    assert local_ctx('gemma-e2b') == 4096, 'a per-model override must not move the others'


# ---- what the engine says on its way past ----------------------------------
def _native_write(text):
    "Write straight to fd 2, the way a C++ engine does -- around Python's sys.stderr, not through it."
    os.write(2, text.encode())


def test_a_native_complaint_is_captured_and_still_printed():
    "Captured for the IDE, and teed to where it was going, because a terminal session still wants it."
    with captured() as cap:
        _native_write(GEMMA)
    assert 'exceed the maximum number of tokens 4096' in cap.text
    assert cap.problems, 'a line saying "exceed" is a problem, not chatter'


def test_engine_chatter_is_not_reported_as_a_problem():
    "An engine that logs delegate creation on every call would otherwise bury the one line that matters."
    with captured() as cap:
        _native_write('INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\n')
    assert cap.text and not cap.problems


def test_captured_output_is_deduplicated_and_trimmed():
    "A native layer will repeat itself once per token; a status bar cannot."
    assert interesting(GEMMA * 5) == [GEMMA.strip()]
    assert len(interesting('\n'.join(f'error {i}' for i in range(20)))) == 4


def test_the_descriptor_survives_an_exception_inside_the_block():
    "A broken stderr would be a far worse bug than the one this fixes."
    before = os.dup(2)
    try:
        with pytest.raises(ValueError):
            with captured():
                _native_write('something\n')
                raise ValueError('boom')
        _native_write('')                       # fd 2 is still writable
        assert sys.stderr is not None
    finally: os.close(before)


def test_an_exception_carries_what_the_engine_said():
    "So the reported failure is the engine's own words rather than a generic wrapper message."
    def boom():
        _native_write(GEMMA)
        raise RuntimeError('generate failed')
    with pytest.raises(RuntimeError) as e: native_capture(boom)
    assert 'exceed the maximum number of tokens' in getattr(e.value, 'native_output', '')


def test_capture_can_be_switched_off(monkeypatch):
    "Anything that moves a file descriptor needs a way out."
    monkeypatch.setenv('LEELA_NO_NATIVE_CAPTURE', '1')
    with captured() as cap: _native_write('x\n')
    assert cap.text == ''


# ---- and how the harness reports it ----------------------------------------
@pytest.fixture
def muttering():
    from ramabana.models import ModelSpec
    return MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))


def test_a_silent_failure_is_reported_rather_than_shown_as_an_empty_answer(muttering):
    """The bug as the user met it: a turn that produced nothing and said nothing about it.

    A stream with no chunks used to end with a blank pane and a cheerful status line. Now
    the last thing the engine said comes out as the answer.
    """
    out = ''.join(muttering.stream('hello'))
    assert 'exceed the maximum number of tokens 4096' in out
    assert muttering.problems


def test_a_cheap_job_that_fails_still_says_so(muttering):
    """`oneshot` returns '' by contract -- completion, classification and compaction all
    need a value, not an exception -- so the failure has to be recorded somewhere else."""
    assert muttering.oneshot('summarise this') == ''
    assert any('input too long' in p for p in muttering.problems)
