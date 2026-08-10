"""A model whose chat template opens `<think>` for it, and never emits the opening tag.

Rishi's stream splitter waits for a `<think>` to know it is inside a thought, so for these
models the deliberation arrives as ordinary reply text and only the closing tag comes back --
once per step. These tests pin the detection, the filter and the shared one-shot cap without
loading a model.
"""
from ramabana.core import resolve
from ramabana.runtime import ONESHOT_TOKENS, RishiBackend, ThinkFilter, answer_only, prefills_think


class FakeTok:
    "Just enough tokenizer to answer `apply_chat_template`."
    def __init__(self, tail): self.tail = tail
    def apply_chat_template(self, msgs, **kw): return '<|im_start|>assistant\n' + self.tail


class FakeChat:
    def __init__(self, tail): self.tokenizer = FakeTok(tail)


def chunks(*texts): return [{'content': [{'type': 'text', 'text': t}]} for t in texts]
def text_of(chunks): return ''.join(
    p.get('text', '') for c in chunks for p in (c.get('content') or []) if p.get('type') == 'text')


# -- detection ---------------------------------------------------------------
def test_an_unclosed_template_think_block_is_detected():
    assert prefills_think(FakeChat('<think>\n')) is True


def test_a_closed_or_absent_think_block_is_not():
    assert prefills_think(FakeChat('<think>\n\n</think>\n\n')) is False   # enable_thinking=False
    assert prefills_think(FakeChat('')) is False                          # not a reasoning model


def test_detection_never_raises():
    class Boom:
        def apply_chat_template(self, *a, **kw): raise RuntimeError('no template')
    bad = FakeChat('')
    bad.tokenizer = Boom()
    assert prefills_think(bad) is False
    assert prefills_think(None) is False          # a backend that never started


# -- filtering ---------------------------------------------------------------
def test_thinking_is_dropped_and_the_answer_survives():
    f = ThinkFilter()
    out = list(f(chunks('Six sevens', ' are 42.\n</th', 'ink>\n\n', '42')))
    assert text_of(out) == '42'
    assert (f.thought, f.answer) == (29, 2)     # `thought` counts the buffered tag too


def test_each_tool_call_re_arms_the_filter():
    "The template opens a fresh thought per step, so one strip per turn is not enough."
    tool = {'content': [{'type': 'tool_call', 'name': 'search_code', 'arguments': {}}]}
    out = list(ThinkFilter()(chunks('think 1', '</think>', 'calling ') + [tool]
                             + chunks('think 2', '</think>', 'done')))
    assert text_of(out) == 'calling done'
    assert out[1] is tool                        # the call itself is passed through untouched


def test_thinking_that_never_answers_is_visible_to_the_caller():
    f = ThinkFilter()
    assert text_of(list(f(chunks('deliberating', '</think>\n\n')))) == ''
    assert (f.thinking, f.answer) == (False, 0)   # what `_stream` reports as a problem
    g = ThinkFilter()
    assert text_of(list(g(chunks('cut off at the cap')))) == ''
    assert (g.thinking, g.answer) == (True, 0)


def test_the_blocking_path_agrees_with_the_streamed_one():
    "`answer_only` and `ThinkFilter` must not disagree about where the reply starts."
    for raw in ('thinking\n</think>\n\n42', '<think>thinking</think>42'):
        assert answer_only(raw) == '42'
    assert text_of(list(ThinkFilter()(chunks('thinking\n</think>\n\n42')))) == '42'


# -- the shared one-shot conversation ---------------------------------------
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

    b = Local(resolve('ornith-9b'))
    b._oneshot_chat = Chat()
    b.start()
    b.oneshot('label this', 'pick one', 32)
    b.oneshot('summarise this')
    assert caps == [32, ONESHOT_TOKENS]
