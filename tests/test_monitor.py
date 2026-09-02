"""Watching a folder something else is changing: what counts as a change, and where the review goes.

The case is a second agent editing the same checkout while a conversation is open, so the
contracts that matter are about *not* wasting a review: nothing already in the folder is a change,
a burst of edits is one change, and a review reaches the next turn exactly once.

Nothing here loads a model. The reviewing sub-agent is a `FakeBackend`, and what it was asked is
read back off it.
"""
import pytest

from ramabana.core import AgentError
from ramabana.monitor import (DFLT_SETTLE, REVIEW_SP, FolderWatch, Monitors, changed, files_under,
                              monitor_tools, report, review_notice, snapshot, summarise)
from ramabana.testing import FakeBackend, MemHost, SPEC, fake_agent
from ramabana.tools import LocalHost, failed


def host(**files):
    "A `MemHost` over `/proj`, with the named files in it."
    return MemHost({f'/proj/{k}': v for k, v in files.items()} or {'/proj/a.py': 'one\n'})


def monitors(h=None, backend=None, **kw):
    "A `Monitors` whose reviews go to one `FakeBackend`, so what was asked can be read back."
    be = backend if backend is not None else FakeBackend(SPEC)
    return Monitors(h or host(), get_backend=lambda: be, **kw), be


def tools(m): return {t.__name__: t for t in monitor_tools(lambda: m)}


# -- what counts as a change ----------------------------------------------------------------

def test_the_first_look_is_a_baseline_so_nothing_already_there_is_reviewed():
    """Opening a watch on a repo must not review the repo. The snapshot `add` takes is the
    baseline, and only what moves after it is a change."""
    m, be = monitors(host(**{'a.py': 'one\n', 'b.py': 'two\n'}))
    w = m.add('/proj', 'Review each change.')
    assert len(w.snap) == 2
    assert m.check() == []
    assert be.spawned == []          # nothing was asked of a model
    assert m.drain() == []


def test_an_added_an_edited_and_a_removed_file_each_reach_the_review():
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review each change.')

    h.write('/proj/a.py', 'ONE\n')
    edited, = m.check(force=True)
    assert (edited['summary'], edited['files']) == ('1 edited', 1)
    assert '-one' in edited['changes'] and '+ONE' in edited['changes']

    h.write('/proj/b.py', 'two\n')
    added, = m.check(force=True)
    assert added['summary'] == '1 added'

    del h.files['/proj/b.py']
    removed, = m.check(force=True)
    assert removed['summary'] == '1 removed'


def test_a_settle_window_folds_a_burst_of_edits_into_one_review():
    """One agent writing four files is one change. Reviewing each write separately spends four
    model calls to say the same thing, and shows the reviewer a quarter of the change each time."""
    h = host(**{'a.py': 'one\n'})
    m, be = monitors(h)
    m.add('/proj', 'Review each change.', settle='10m')

    h.write('/proj/a.py', 'ONE\n')
    assert len(m.check()) == 1
    for name in ('b.py', 'c.py', 'd.py'): h.write(f'/proj/{name}', 'x\n')
    assert m.check() == []                      # still inside the window
    assert len(be.spawned) == 1

    rest, = m.check(force=True)                 # a tool call looks anyway
    assert rest['summary'] == '3 added'


def test_a_settle_of_zero_reviews_every_check():
    m, _ = monitors(h := host(**{'a.py': 'one\n'}))
    m.add('/proj', 'Review.', settle='0')
    h.write('/proj/a.py', 'two\n')
    assert len(m.check()) == 1
    h.write('/proj/a.py', 'three\n')
    assert len(m.check()) == 1


def test_a_pattern_limits_the_watch_to_matching_files():
    h = host(**{'a.py': 'one\n', 'notes.md': 'hello\n'})
    m, _ = monitors(h)
    w = m.add('/proj', 'Review the Python.', pattern='*.py')
    assert set(w.snap) == {'/proj/a.py'}

    h.write('/proj/notes.md', 'goodbye\n')
    assert m.check(force=True) == []            # not a watched file

    h.write('/proj/b.py', 'two\n')
    rec, = m.check(force=True)
    assert rec['summary'] == '1 added'


def test_a_watch_can_name_one_file():
    h = host(**{'a.py': 'one\n', 'b.py': 'two\n'})
    m, _ = monitors(h)
    w = m.add('/proj/a.py', 'Review this file.')
    assert set(w.snap) == {'/proj/a.py'}
    h.write('/proj/b.py', 'TWO\n')
    assert m.check(force=True) == []

    h.write('/proj/a.py', 'ONE\n')
    rec, = m.check(force=True)
    assert 'edited   a.py' in rec['changes']       # named, not the '.' a bare relative_to gives


def test_a_folder_outside_the_open_folders_is_refused(tmp_path):
    "The sandbox is the host's, and a folder watch is not the way around it."
    root = tmp_path/'proj'
    (root).mkdir()
    (root/'a.py').write_text('one\n')
    m = Monitors(LocalHost([root], web=False, index=False))
    with pytest.raises(AgentError): m.add(tmp_path/'elsewhere', 'Review.')
    assert m.all() == []

    w = m.add(root, 'Review.')
    assert set(w.snap) == {str(root/'a.py')}


def test_a_watch_needs_instructions_because_they_are_all_the_reviewer_gets():
    m, _ = monitors()
    with pytest.raises(AgentError): m.add('/proj', '   ')
    assert m.all() == []


# -- what the reviewer is asked -------------------------------------------------------------

def test_the_reviewer_gets_the_standing_brief_and_the_diff_and_cannot_see_the_conversation():
    h = host(**{'a.py': 'one\n'})
    m, be = monitors(h)
    m.add('/proj', 'Report anything that breaks a contract in tests/.')
    h.write('/proj/a.py', 'two\n')
    rec, = m.check(force=True)

    sub, = be.spawned
    asked = str(sub.sent[0])
    assert asked.startswith('Report anything that breaks a contract in tests/.')
    assert '-one' in asked and '+two' in asked and 'a.py' in asked
    assert sub.sp == REVIEW_SP, 'the reviewer got the research briefing, not the review one'
    assert rec['review'] == 'sub answer'


def test_a_reviewing_sub_agent_cannot_write_and_cannot_open_another_watch():
    """Two writers on one tree is how work gets lost, and a watch opened by a sub-agent outlives
    the task that opened it. Both are stripped by `read_only` before the reviewer sees a tool."""
    def named(n):
        def f(): return n
        f.__name__ = n
        return f
    given = [named(n) for n in ('view_file', 'edit_file', 'run_shell', 'watch_folder',
                                'check_folders', 'delegate_search')]
    h = host(**{'a.py': 'one\n'})
    m, be = monitors(h, get_tools=lambda: given)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    m.check(force=True)

    sub, = be.spawned
    assert {t.__name__ for t in sub.tools} == {'view_file'}


def test_a_monitor_with_no_model_still_reports_what_changed():
    "No backend is not an error: the change report is the answer, and it still reaches the turn."
    h = host(**{'a.py': 'one\n'})
    m = Monitors(h)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    rec, = m.check(force=True)
    assert rec['status'] == 'unreviewed' and rec['review'] == ''
    assert '+two' in rec['changes']
    assert '+two' in review_notice(m.drain())


# -- where the review goes ------------------------------------------------------------------

def test_the_snapshot_advances_even_when_the_review_fails():
    """A review that raises must not leave the change pending. Otherwise a model that keeps
    failing turns one edit into a diff that grows for the rest of the session."""
    h = host(**{'a.py': 'one\n'})
    m = Monitors(h, get_backend=lambda: object())      # has no `spec`, so `delegate` raises
    w = m.add('/proj', 'Review.', settle='0')
    h.write('/proj/a.py', 'two\n')

    bad, = m.check()
    assert bad['status'] == 'error' and bad['error'] and w.last_status == 'error'
    assert m.check() == []                              # the change was consumed, not retried
    assert w.snap['/proj/a.py'] == 'two\n'


def test_a_check_already_running_is_not_paid_for_twice():
    """The background tick starts at the top of a turn, and the model can call `check_folders`
    during it. Both finding the same change means two reviews and two bills for one edit."""
    h = host(**{'a.py': 'one\n'})
    m, be = monitors(h)
    m.add('/proj', 'Review.', settle='0')
    h.write('/proj/a.py', 'two\n')

    m.checking.acquire()                             # as a tick holds it
    try:
        assert m.check(block=False) is None          # `None`, not `[]`: somebody else is looking
        assert be.spawned == []
        assert tools(m)['check_folders']() == (
            'a review is already running; its answer arrives on your next turn')
    finally:
        m.checking.release()

    rec, = m.check()                                 # and the change is still there to review
    assert rec['summary'] == '1 edited'


def test_a_drained_review_never_reaches_a_second_turn():
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review.', settle='0')
    h.write('/proj/a.py', 'two\n')
    m.check()
    assert len(m.drain()) == 1
    assert m.drain() == []
    assert review_notice([]) == ''


def test_a_review_is_filed_into_durable_memory_when_the_host_has_any():
    class Remembering(MemHost):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.notes, self.remembered = [], []
        def note(self, text): self.notes.append(text)
        def remember(self, text, title=None, tags=()):
            self.remembered.append((text, title, list(tags)))
            return {'doc_id': 'd1'}

    h = Remembering({'/proj/a.py': 'one\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    m.check(force=True)

    (text, title, tags), = h.remembered
    assert text == 'sub answer' and 'folder review' in title and tags == ['folder-review']
    assert any('folder review' in n for n in h.notes)


def test_a_host_without_memory_still_gets_its_review():
    "`remember` raising `NotImplementedError` is the common case, not a failure to report."
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    rec, = m.check(force=True)
    assert rec['review'] == 'sub answer' and m.drain() == [rec]


def test_only_the_newest_reviews_are_held_for_the_next_turn():
    "A session nobody came back to must not grow a queue without bound."
    from ramabana.monitor import PENDING_MAX
    h = host(**{'a.py': '0\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review.', settle='0')
    for i in range(PENDING_MAX + 3):
        h.write('/proj/a.py', f'{i}\n')
        m.check()
    assert len(m.drain()) == PENDING_MAX


def test_on_review_gets_every_record_and_a_frontend_that_raises_is_ignored():
    seen = []
    def hook(rec):
        seen.append(rec)
        raise RuntimeError('the frontend is not the monitor\'s problem')
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h, on_review=hook)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    rec, = m.check(force=True)
    assert seen == [rec]


# -- the tools -------------------------------------------------------------------------------

def test_the_folder_tools_open_list_and_cancel_a_watch():
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h)
    ts = tools(m)
    assert 'no folder is being watched' in ts['list_folder_watches']()
    assert ts['check_folders']() == 'no folder is being watched'

    said = ts['watch_folder']('/proj', 'Review each change.')
    assert '/proj' in said and '1 files' in said
    wid = m.all()[0].id
    assert wid in ts['list_folder_watches']()

    assert ts['cancel_folder_watch']('nope').startswith('no such folder watch')
    assert ts['cancel_folder_watch'](wid) == f'stopped watching {wid}'
    assert m.all() == []


def test_check_folders_ignores_the_settle_window_and_reports_each_review_once():
    h = host(**{'a.py': 'one\n'})
    m, _ = monitors(h)
    ts = tools(m)
    ts['watch_folder']('/proj', 'Review each change.', '', '10m')
    assert ts['check_folders']() == 'nothing has changed since the last look'

    h.write('/proj/a.py', 'two\n')
    out = ts['check_folders']()
    assert 'sub answer' in out and '1 edited' in out
    assert ts['check_folders']() == 'nothing has changed since the last look'
    assert m.drain() == []                       # reported, so the next turn must not repeat it


def test_a_refused_folder_comes_back_as_a_tool_error_not_an_exception(tmp_path):
    (tmp_path/'proj').mkdir()
    m = Monitors(LocalHost([tmp_path/'proj'], web=False, index=False))
    said = tools(m)['watch_folder'](str(tmp_path/'elsewhere'), 'Review.')
    assert failed(said) and 'could not watch that folder' in said
    assert m.all() == []


# -- the session ------------------------------------------------------------------------------

def test_a_session_offers_the_folder_tools_and_briefs_the_model_on_them():
    a, _ = fake_agent()
    assert {'watch_folder', 'list_folder_watches', 'cancel_folder_watch',
            'check_folders'} <= {t.__name__ for t in a.tools}
    assert '`watch_folder` is for work happening beside this conversation' in a.system_prompt()


def test_a_review_reaches_the_next_prompt_exactly_once():
    a, be = fake_agent(replies=['ok', 'ok', 'ok'])
    a.monitors.add('/proj', 'Review each change.', settle='0')
    a.host.write('/proj/a.py', 'changed\n')
    a.monitors.check()

    a.ask('what happened?')
    carried = str(be.sent[-1])
    assert '<folder-review' in carried and 'sub answer' in carried

    a.ask('and now?')
    assert '<folder-review' not in str(be.sent[-1])


def test_the_background_look_leaves_its_review_for_the_next_turn():
    "`poll_monitors` is the tick a turn starts. Its reviews are read by the turn after it."
    a, _ = fake_agent(replies=['ok'])
    assert a.poll_monitors() is None                  # nothing watched, so no thread
    a.monitors.add('/proj', 'Review each change.', settle='0')
    a.host.write('/proj/a.py', 'changed\n')
    a.poll_monitors().join(timeout=10)
    rec, = a.monitors.drain()
    assert rec['status'] == 'ok' and rec['summary'] == '1 edited'


# -- the pieces -------------------------------------------------------------------------------

def test_the_snapshot_helpers_answer_on_their_own():
    h = host(**{'a.py': 'one\n', 'b.md': 'two\n'})
    assert [p.name for p in files_under(h, '/proj')] == ['a.py', 'b.md']
    assert [p.name for p in files_under(h, '/proj', '*.py')] == ['a.py']
    assert [p.name for p in files_under(h, '/proj', '*.py, *.md')] == ['a.py', 'b.md']

    before = snapshot(h, '/proj')
    h.write('/proj/a.py', 'ONE\n')
    del h.files['/proj/b.md']
    h.write('/proj/c.py', 'three\n')
    chg = changed(before, snapshot(h, '/proj'))
    assert summarise(chg) == '1 added, 1 edited, 1 removed'

    text = report(chg, '/proj')
    assert 'edited   a.py  +1/-1' in text
    assert 'removed  b.md' in text and 'added    c.py' in text
    assert '+three' in text


def test_a_file_too_large_to_diff_is_tracked_by_its_size():
    from ramabana.monitor import SNAP_MAX_BYTES
    h = host(**{'big.txt': 'x' * (SNAP_MAX_BYTES + 1)})
    before = snapshot(h, '/proj')
    assert 'too large to diff' in before['/proj/big.txt']
    h.write('/proj/big.txt', 'y' * (SNAP_MAX_BYTES + 2))
    assert list(changed(before, snapshot(h, '/proj'))) == ['/proj/big.txt']


def test_a_watch_repr_says_what_it_is_watching():
    w = FolderWatch('/proj', 'Review.', settle=DFLT_SETTLE)
    assert w.id.startswith('fw_') and '/proj' in repr(w) and w.settle == 20
