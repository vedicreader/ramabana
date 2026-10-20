"""Sub-agent limits: steps, a wall clock, bounded nesting, background runs in `runs`, and pruned run children."""
import re, threading, time
from pathlib import Path
from fastcore.basics import AttrDict
from ramabana.runtime import Run
from ramabana.tools import subagent_tools, Slots, Background, MAX_TOOL_CHARS
from ramabana.testing import FakeBackend


def view_file(path: str) -> str:
    "A read tool."
    return 'x=1'


def _subs(be, **kw): return {t.__name__: t for t in subagent_tools(lambda: be, lambda: [view_file], **kw)}


def _stepping(be):
    "Give `be`'s sub-agents the `max_steps` a rishi chat has."
    spawn = be.spawn
    be.spawn = lambda **kw: setattr(s := spawn(**kw), 'max_steps', 0) or s
    return be


def test_a_delegations_max_steps_is_capped_by_the_session_and_floored():
    """A turn model asked for five or eight steps, and its sub-agents ran out before they could report.
    A delegation gets at least `SUB_MAX_STEPS`, within the session's cap, and is told the budget notice is ours."""
    from ramabana.tools import SUB_MAX_STEPS, sub_briefing
    be = _stepping(FakeBackend())
    subs = _subs(be, get_steps=lambda: 20)
    for n in (50, 3, 0): subs['delegate_search'](['q'], max_steps=n)
    _subs(be, get_steps=lambda: 5)['delegate_search'](['q'], max_steps=3)
    _subs(be, get_steps=lambda: 80)['delegate_search'](['q'], max_steps=3)
    assert [s.max_steps for s in be.spawned] == [20, min(SUB_MAX_STEPS, 20), 20, 5, SUB_MAX_STEPS]
    assert 'budget' in sub_briefing() and 'harness' in sub_briefing()


class _Hung:
    "A sub-agent that never answers until it is cancelled."
    max_steps = 0
    def __init__(self): self.release = threading.Event()
    def send(self, q, run=None): self.release.wait(10); return 'late'
    def cancel(self): self.release.set(); return True
    def close(self): pass


def test_each_hung_worker_is_stopped_by_its_own_time_limit():
    be = AttrDict(spec=AttrDict(name='fake', local=False), spawn=lambda **kw: _Hung())
    subs = _subs(be, get_timeout=lambda: .2)
    t0 = time.monotonic()
    out = subs['delegate_search'](['a', 'b', 'c'])
    assert time.monotonic() - t0 < 5
    assert out.count('time limit') == 3, out


def test_a_sub_agent_waiting_on_its_own_sub_agents_lends_its_slot():
    s, parent, kid = Slots(1), Run('p'), Run('k')
    with s.hold(parent) as ok:
        assert ok
        with s.lend(parent):
            with s.hold(kid) as got: assert got, 'the child waited on a slot its parent held'
        assert parent.slot


class _Answers:
    "A sub-agent that answers a question starting `long` with 20000 characters, and any other briefly."
    max_steps = 0
    def send(self, q, run=None): return 'A' * 20000 if q.startswith('long') else f'short answer to {q}'
    def close(self): pass


def _answering(**kw):
    be = AttrDict(spec=AttrDict(name='fake', local=True), spawn=lambda **k: _Answers())
    return _subs(be, **kw)


def test_every_question_keeps_its_own_share_of_the_combined_answer():
    out = _answering()['delegate_search'](['long one', 'second', 'third'])
    assert 'short answer to second' in out and 'short answer to third' in out, out[-300:]
    assert len(out) <= MAX_TOOL_CHARS


def test_a_clipped_answer_is_saved_whole_and_the_note_names_the_file(tmp_path):
    subs = _answering(get_log_dir=lambda: tmp_path)
    out = subs['delegate_search'](['long one'])
    assert len(out) <= MAX_TOOL_CHARS
    saved = list(tmp_path.glob('*.txt'))
    assert len(saved) == 1 and saved[0].read_text() == 'A' * 20000
    assert f'saved to {saved[0]}' in out and 'view_file' in out
    subs['delegate_search'](['short'])
    assert len(list(tmp_path.glob('*.txt'))) == 1   # an answer that fits is not saved
    out = subs['delegate_search'](['long a', 'long b'])
    assert len(list(tmp_path.glob('*.txt'))) == 3 and out.count('saved to') == 2


def test_without_a_log_dir_the_full_answer_is_still_saved_somewhere_readable():
    out = _answering()['delegate_search'](['long one'])
    path = Path(re.search(r'saved to (\S+?\.txt)', out).group(1))
    assert path.read_text() == 'A' * 20000


def test_delegation_output_follows_the_effective_cap_not_the_default(tmp_path):
    "A 2000-char model was sent 6000-char delegations, and the outer cut removed the note naming the saved file."
    bg = Background()
    subs = _answering(get_log_dir=lambda: tmp_path, get_max=lambda: 2000, background=bg)
    for qs in (['long one'], ['long a', 'second', 'third']):
        out = subs['delegate_search'](qs)
        assert len(out) <= 2000 and 'saved to' in out, (len(out), out[-200:])
    rid = re.search(r'run_\w+', subs['delegate_async']('long one')).group()
    deadline = time.monotonic() + 5
    while rid not in bg.answers and time.monotonic() < deadline: time.sleep(.01)
    page = subs['delegate_result'](rid)
    assert len(page) <= 2000 and 'continue with offset=' in page


def test_a_long_skill_note_fits_the_cap_and_a_tiny_cap_still_pages_forward(tmp_path):
    "A note naming thousands of missing skills went past the cap; a cap below the continuation note never advanced."
    subs = _answering(get_log_dir=lambda: tmp_path, get_max=lambda: 1500, get_skills=lambda: [])
    out = subs['delegate_search'](['short'], skills=' '.join(f'missing{i}' for i in range(2000)))
    assert len(out) <= 1500 and 'short answer to short' in out, (len(out), out[:200])
    bg = Background()
    tiny = _answering(get_max=lambda: 10, background=bg)
    rid = re.search(r'run_\w+', tiny['delegate_async']('long one')).group()
    deadline = time.monotonic() + 5
    while rid not in bg.answers and time.monotonic() < deadline: time.sleep(.01)
    nxt = lambda page: int(re.search(r'continue with offset=(\d+)\]$', page).group(1))
    first = nxt(tiny['delegate_result'](rid))
    assert 0 < first < nxt(tiny['delegate_result'](rid, offset=first))


def test_a_sub_agent_is_briefed_with_its_family_notes_and_its_answer_budget():
    "The parent pasted the GPT notes and a reporting rule into every question; the briefing now carries both."
    spawned = []
    be = AttrDict(spec=AttrDict(name='gpt-6-sol', local=False), spawn=lambda **k: spawned.append(k['sp']) or _Answers())
    subs = _subs(be, get_max=lambda: 3000, get_notes=lambda spec: f'## Working as {spec.name}')
    subs['delegate_search'](['q'])
    subs['delegate_search'](['a', 'b'])
    assert len(spawned) == 3 and all('## Working as gpt-6-sol' in sp for sp in spawned), spawned[0]
    assert '3000 characters' in spawned[0] and all('1499 characters' in sp for sp in spawned[1:]), 'each answer is told its share'
    assert 'report file' in spawned[0]


def test_delegate_result_reads_a_long_answer_in_pages_by_offset():
    bg = Background()
    subs = _answering(background=bg)
    rid = re.search(r'run_\w+', subs['delegate_async']('long one')).group()
    deadline = time.monotonic() + 5
    while rid not in bg.answers and time.monotonic() < deadline: time.sleep(.01)
    got, offset = '', 0
    for _ in range(10):
        page = subs['delegate_result'](rid, offset=offset)
        assert len(page) <= MAX_TOOL_CHARS
        more = re.search(r'continue with offset=(\d+)\]$', page)
        got += re.sub(r'…\[chars .*\]$', '', page)
        if more is None: break
        offset = int(more.group(1))
    assert got == 'A' * 20000 and offset > 0, (len(got), offset)
    assert 'offset' in subs['delegate_result'](rid)
    assert 'past the end' in subs['delegate_result'](rid, offset=99999)


def create_file(path: str, content: str) -> str:
    "A write tool."
    return 'wrote'


class _Overlap:
    "A backend whose sub-agents note how many of them work at once, and what each was handed."
    def __init__(self):
        self.spec, self.lock, self.now, self.peak, self.handed, self.ctx = AttrDict(name='fake', local=False), threading.Lock(), 0, 0, [], []
    def spawn(self, tools=(), **kw):
        self.handed.append(({t.__name__ for t in tools}, kw.get('approve')))
        be = self
        class Sub:
            max_steps = 0
            def send(self, q, run=None):
                from ramabana.tools import SUB_READ_ONLY
                with be.lock: be.now += 1; be.peak = max(be.peak, be.now)
                be.ctx.append(SUB_READ_ONLY.get())
                time.sleep(.3)
                with be.lock: be.now -= 1
                return 'found it'
            def close(self): pass
        return Sub()


def _writing(be): return {t.__name__: t for t in subagent_tools(lambda: be, lambda: [view_file, create_file], get_writes=lambda: True, get_approve=lambda: (lambda tc: True))}


def test_read_only_questions_run_at_once_even_when_sub_agents_may_write():
    "Sub-agents may write by default, and writing ones run one after another, so four read-only questions took four turns of waiting."
    be = _Overlap()
    out = _writing(be)['delegate_search'](['a', 'b', 'c'], writes=False)
    assert out.count('found it') == 3 and be.peak > 1, be.peak
    assert all(names == {'view_file'} and approve is None for names, approve in be.handed), be.handed
    assert be.ctx == [True] * 3, 'a nested delegation inherits read-only'


def test_sub_agents_that_may_write_still_run_one_after_another():
    be = _Overlap()
    _writing(be)['delegate_search'](['a', 'b'])
    assert be.peak == 1 and all('create_file' in names for names, _ in be.handed)


def test_a_read_only_delegation_cannot_start_a_writing_one_below_it():
    from ramabana.tools import SUB_READ_ONLY
    tok = SUB_READ_ONLY.set(True)
    try: assert 'read-only' in _writing(_Overlap())['delegate_async']('q', writes=True)
    finally: SUB_READ_ONLY.reset(tok)
