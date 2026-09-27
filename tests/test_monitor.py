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
                              report, review_notice, snapshot, summarise)
from ramabana.testing import FakeBackend, MemHost, SPEC, fake_agent
from ramabana.tools import NO_SUB, LocalHost, MemoryHost, WatchHost, failed, read_only, tools_for, watch_tools


def host(**files):
    "A `MemHost` over `/proj`, with the named files in it."
    return MemHost({f'/proj/{k}': v for k, v in files.items()} or {'/proj/a.py': 'one\n'})


def monitors(h=None, backend=None, **kw):
    "A `Monitors` whose reviews go to one `FakeBackend`, so what was asked can be read back."
    be = backend if backend is not None else FakeBackend(SPEC)
    return Monitors(h or host(), get_backend=lambda: be, **kw), be


class VaultLike(MemHost, MemoryHost, WatchHost):
    "A host whose watches table is a list; what `Monitors.sync` reads. Memory is the notes it was handed."
    def __init__(self, files): super().__init__(files); self.rows, self.notes = [], []
    def watch(self, target, action='remind', every='1d', note=None, **params):
        w = dict(id=f'w{len(self.rows)+1}', kind=action, action=action, target=target, every=86400, note=note,
                 runs=0, last_status='', **params)
        self.rows.append(w); return w
    def watches(self, due_only=False): return list(self.rows)
    def unwatch(self, wid): self.rows = [r for r in self.rows if r['id'] != wid]; return True
    def poll(self): return {'checked': 0, 'ran': 0, 'results': []}
    def remember(self, text, title=None, tags=(), key=''): self.notes.append((title, key, text)); return dict(doc_id='d1', title=title)
    def memory_search(self, query, limit=8): return []
    def memory_tree(self, document=''): return []
    def memory_read(self, node_id): return {}
    def memory_forget(self, doc_id): return False
    watch_actions = ('url', 'remind', 'web', 'folder')


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
    assert sub.sp.startswith(REVIEW_SP), 'the reviewer got the research briefing, not the review one'
    assert rec['review'] == 'sub answer'


def test_a_reviewing_sub_agent_cannot_write_and_cannot_open_another_watch():
    """Two writers on one tree is how work gets lost, and a watch opened by a sub-agent outlives
    the task that opened it. Both are stripped by `read_only` before the reviewer sees a tool."""
    def named(n):
        def f(): return n
        f.__name__ = n
        return f
    given = [named(n) for n in ('view_file', 'replace_text', 'run_shell', 'watch',
                                'cancel_watch', 'delegate_search')]
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
        def remember(self, text, title=None, tags=(), key=''):
            self.remembered.append((text, title, list(tags), key))
            return {'doc_id': 'd1'}

    h = Remembering({'/proj/a.py': 'one\n'})
    m, _ = monitors(h)
    m.add('/proj', 'Review.')
    h.write('/proj/a.py', 'two\n')
    m.check(force=True)

    (text, title, tags, key), = h.remembered
    assert text == 'sub answer' and 'folder review' in title and tags == ['folder-review'] and key.startswith('folder-review:fw_')
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


# -- the tools: shalya's `watch(kind='folder')` on the vault, reviewed here ------------------------

def test_a_folder_watch_opened_through_the_vault_is_reviewed_by_the_harness():
    """The model opens a folder watch with the one `watch` tool; the row lives in the vault. The harness
    mirrors those rows, takes the baseline on first sight, reviews with a read-only sub-agent and files
    each review under one key per watch, so the latest review replaces the last."""
    h = VaultLike({'/proj/a.py': 'one\n'})
    m, be = monitors(h)
    wt = {t.__name__: t for t in watch_tools(h)}
    said = wt['watch']('/proj', kind='folder', instructions='Review each change.', pattern='*.py')
    assert said.startswith('watching folder /proj as w1')
    assert [w.id for w in m.all()] == []                     # nothing seen until the harness looks
    assert m.check(force=True) == [] and [w.id for w in m.all()] == ['w1']   # first look snapshots, reviews nothing
    h.write('/proj/a.py', 'two\n')
    rec, = m.check(force=True)
    assert rec['watch_id'] == 'w1' and rec['review'] == 'sub answer'
    assert h.notes[-1][:2] == ('folder review: proj: 1 edited', 'folder-review:w1')
    assert 'w1' in wt['list_watches']()
    assert wt['cancel_watch']('w1') == 'cancelled w1' and m.check() == [] and m.all() == []


def test_a_folder_watch_outside_the_open_folders_is_reported_not_raised():
    h = VaultLike({'/proj/a.py': 'one\n'})
    h.check = lambda path, must_exist=False, reading=False: (_ for _ in ()).throw(AgentError(f'outside the open folders: {path}'))
    m, _ = monitors(h)
    h.watch('/elsewhere', action='folder', instructions='Review.')
    assert m.check(force=True) == [] and m.all() == []


def test_a_session_without_a_vault_offers_no_folder_tools_but_the_monitor_api_still_works():
    a, _ = fake_agent()
    names = {t.__name__ for t in a.tools}
    assert not ({'watch_folder', 'check_folders', 'list_folder_watches', 'cancel_folder_watch', 'watch'} & names)
    assert '`watch(' not in a.system_prompt()                                     # the rule appears only with the tool
    a.monitors.add('/proj', 'Review.')                                            # the beat and tests keep this
    assert [w.folder for w in a.monitors.all()] == ['/proj']
    assert 'watching' in a.watch()


def test_a_vault_session_offers_watch_and_no_sub_agent_can_open_one():
    "Review Focus: a reviewing or delegated sub-agent never gets a watch-creating tool."
    a, _ = fake_agent(VaultLike({'/proj/a.py': 'one\n'}))
    names = {t.__name__ for t in a.tools}
    assert {'watch', 'list_watches', 'cancel_watch'} <= names and 'remember_note' not in names   # (the small fake model's budget drops the memory group)
    assert '`watch(target, kind=' in a.system_prompt()
    sub = {t.__name__ for t in read_only(a._sub_plain(), block=NO_SUB)}
    assert not (sub & {'watch', 'cancel_watch', 'watch_folder', 'check_folders'}) and 'list_watches' in sub
    assert not (sub & NO_SUB)


# -- the session ------------------------------------------------------------------------------

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
