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
    A delegation gets at least `SUB_MIN_STEPS`, within the session's cap, and is told the budget notice is ours."""
    from ramabana.tools import SUB_MIN_STEPS
    be = _stepping(FakeBackend())
    subs = _subs(be, get_steps=lambda: 20)
    for n in (50, 3, 0): subs['delegate_search'](['q'], max_steps=n)
    _subs(be, get_steps=lambda: 5)['delegate_search'](['q'], max_steps=3)
    _subs(be, get_steps=lambda: 80)['delegate_search'](['q'], max_steps=3)
    assert [s.max_steps for s in be.spawned] == [20, min(SUB_MIN_STEPS, 20), 20, 5, SUB_MIN_STEPS]


def test_a_request_below_the_cap_is_not_raised_to_it():
    """The floor was `SUB_MAX_STEPS`, so once the session cap equalled it every smaller request ran to the cap."""
    from ramabana.tools import SUB_MAX_STEPS, SUB_MIN_STEPS
    be = _stepping(FakeBackend())
    subs = _subs(be, get_steps=lambda: SUB_MAX_STEPS)
    for n in (SUB_MIN_STEPS + 10, 0, SUB_MAX_STEPS + 5): subs['delegate_search'](['q'], max_steps=n)
    assert [s.max_steps for s in be.spawned] == [SUB_MIN_STEPS + 10, SUB_MAX_STEPS, SUB_MAX_STEPS]


def test_under_auto_a_delegation_may_ask_for_up_to_the_ceiling():
    "Every request was clamped to 80, so a model that asked for 250 silently got a third of it."
    from ramabana.tools import SUB_MAX_STEPS, SUB_STEP_CEILING
    be = _stepping(FakeBackend())
    subs = _subs(be, get_steps=lambda: 'auto')
    for n in (250, 1000, 0): subs['delegate_search'](['q'], max_steps=n)
    assert SUB_STEP_CEILING == 400
    assert [s.max_steps for s in be.spawned] == [250, SUB_STEP_CEILING, SUB_MAX_STEPS]


def test_a_numeric_session_cap_may_pass_80_and_still_caps_every_delegation():
    from ramabana.testing import fake_agent
    a, _ = fake_agent()
    assert a.subagent_steps == 'auto' and 'steps auto' in a.subagent_report
    assert a.set_subagent_steps(150) == 150 and 'steps 150' in a.subagent_report
    be = _stepping(FakeBackend())
    _subs(be, get_steps=lambda: a.subagent_steps)['delegate_search'](['q'], max_steps=250)
    assert [s.max_steps for s in be.spawned] == [150]
    assert (a.set_subagent_steps(9999), a.set_subagent_steps(0), a.set_subagent_steps('auto')) == (400, 1, 'auto')


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
    def send(self, q, run=None): return 'A' * 20000 if q.startswith('long') else f'short answer to {q}\nstate: completed'
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
    assert f'saved to {saved[0]}' in out
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
                return 'found it\nstate: completed'
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


def test_delegate_search_is_read_only_unless_asked_to_write():
    "Several read-only questions run at once, so read-only is the default and `writes=True` asks for the write tools."
    be = _Overlap()
    _writing(be)['delegate_search'](['a', 'b', 'c'])
    assert be.peak > 1 and all(names == {'view_file'} for names, _ in be.handed), be.handed


def test_sub_agents_that_may_write_still_run_one_after_another():
    be = _Overlap()
    _writing(be)['delegate_search'](['a', 'b'], writes=True)
    assert be.peak == 1 and all('create_file' in names for names, _ in be.handed)


def test_a_read_only_delegation_cannot_start_a_writing_one_below_it():
    from ramabana.tools import SUB_READ_ONLY
    tok = SUB_READ_ONLY.set(True)
    try: assert 'read-only' in _writing(_Overlap())['delegate_async']('q', writes=True)
    finally: SUB_READ_ONLY.reset(tok)


def _call_in(run, tool, *a):
    from ramabana.runtime import _current_run
    tok = _current_run.set(run)
    try: return tool(*a)
    finally: _current_run.reset(tok)

def test_under_auto_a_spent_delegation_does_not_starve_the_next_one():
    "Under `auto` every sub-agent of a turn shared 400 calls, so after a few busy delegations each later one was refused on its first call."
    from ramabana.agent import TREE_SPENT
    from ramabana.tools import SUB_STEP_CEILING
    from ramabana.runtime import Run
    allowance = 4 * SUB_STEP_CEILING   # a 400-step delegation must not run out of calls before it runs out of steps
    from ramabana.testing import fake_agent
    a, _ = fake_agent()
    assert a.max_tool_calls is None, 'auto'
    view = next(t for t in a.tools if t.__name__ == 'view_file')
    turn = Run('turn', question='q')
    first = Run('d1', 'child', 'q', 'm', turn)
    for _ in range(allowance): assert _call_in(first, view, '/proj/a.py') != TREE_SPENT
    assert _call_in(first, view, '/proj/a.py') == TREE_SPENT, 'one runaway delegation is still bounded'
    assert _call_in(Run('d1n', 'child', 'q', 'm', first), view, '/proj/a.py') == TREE_SPENT, 'its nested sub-agents share its allowance'
    assert 'def a()' in _call_in(Run('d2', 'child', 'q', 'm', turn), view, '/proj/a.py'), 'the next delegation still works'
    bg = Run('bg', 'background', 'q', 'm')
    for _ in range(allowance): _call_in(Run('bgc', 'child', 'q', 'm', bg), view, '/proj/a.py')
    assert _call_in(bg, view, '/proj/a.py') == TREE_SPENT, 'a background delegation and its children are one allowance'

def test_a_numeric_tool_budget_still_caps_all_of_a_turns_delegations_together():
    from ramabana.agent import TREE_SPENT
    from ramabana.runtime import Run
    from ramabana.testing import fake_agent
    a, _ = fake_agent()
    a.max_tool_calls = 20
    view = next(t for t in a.tools if t.__name__ == 'view_file')
    turn = Run('turn', question='q')
    for _ in range(20): _call_in(Run('d1', 'child', 'q', 'm', turn), view, '/proj/a.py')
    assert _call_in(Run('d2', 'child', 'q', 'm', turn), view, '/proj/a.py') == TREE_SPENT


class _Scripted(FakeBackend):
    "A backend whose sub-agents give `sub_replies` in turn."
    def __init__(self, sub_replies=(), **kw): super().__init__(**kw); self.sub_replies = list(sub_replies)
    def spawn(self, sp='', tools=(), **kw):
        s = super().spawn(sp, tools, **kw); s.replies = list(self.sub_replies); return s

_FINAL = 'Found nothing.\nstate: completed, searched everywhere'


def test_a_status_reply_is_sent_back_once():
    from ramabana.tools import delegate
    be = _Scripted(['Running the tests next.', _FINAL])
    assert delegate(be, 'q') == _FINAL
    sent = be.spawned[0].sent
    assert len(sent) == 2 and 'no tool call' in sent[1] and 'state:' in sent[1], sent


def test_a_second_status_reply_ends_the_run():
    from ramabana.tools import delegate
    be = _Scripted(['Running the tests next.', 'Still running them.'])
    assert delegate(be, 'q') == 'Still running them.'
    assert len(be.spawned[0].sent) == 2


def test_a_final_report_is_not_sent_back():
    from ramabana.tools import delegate
    be = _Scripted([_FINAL])
    assert delegate(be, 'q') == _FINAL
    assert len(be.spawned[0].sent) == 1


def _limits(steps_setting, session_timeout, asked):
    "The `(max_steps, timeout)` a delegation tool passes to `delegate`."
    import ramabana.tools as T
    from unittest.mock import patch
    got = {}
    def fake(*a, **kw): got.update(kw); return 'x'
    be = FakeBackend()
    tools = {t.__name__: t for t in subagent_tools(lambda: be, lambda: [], get_steps=lambda: steps_setting, get_timeout=lambda: session_timeout)}
    with patch.object(T, 'delegate', fake): tools['delegate_search'](['q'], max_steps=asked)
    return got['max_steps'], got['timeout']


def test_under_auto_the_default_timeout_grows_with_the_steps():
    from ramabana.tools import SUB_TIMEOUT
    assert _limits('auto', SUB_TIMEOUT, 80) == (80, 1800)
    assert _limits('auto', SUB_TIMEOUT, 360) == (360, 7200)
    assert _limits('auto', SUB_TIMEOUT, 400) == (400, 8000)


def test_a_timeout_the_session_set_wins_over_the_steps():
    from ramabana.tools import SUB_TIMEOUT
    assert _limits('auto', 600, 80) == (80, 600)
    assert _limits('auto', 600, 360) == (360, 600)
    assert _limits('auto', 0, 360) == (360, 0)
    assert _limits(120, SUB_TIMEOUT, 120) == (120, 1800)
