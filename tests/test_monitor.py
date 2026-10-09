"""Watching a folder something else is changing: what counts as a change, and where the review goes.

The case is a second agent editing the same checkout while a conversation is open, so the
contracts that matter are about *not* wasting a review: nothing already in the folder is a change,
a burst of edits is one change, and a review reaches the next turn exactly once.

Nothing here loads a model. The reviewing sub-agent is a `FakeBackend`, and what it was asked is
read back off it.
"""
from ramabana.monitor import Monitors
from ramabana.testing import FakeBackend, MemHost, SPEC, fake_agent
from ramabana.tools import MemoryHost, WatchHost, failed, tools_for, watch_tools


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


# -- what the reviewer is asked -------------------------------------------------------------

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
