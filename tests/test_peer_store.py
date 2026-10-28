"The peers store: the envelope, the log and the inboxes."
import json, threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from ramabana.control import Control
from ramabana.peers import Envelope, log, peers_dir, post, read_log, take, together_on, together_state, wait_take


def test_envelope_round_trip(tmp_path):
    e = Envelope('ask', 'build Card', {'kind': 'claude', 'session': 's1', 'name': 'abhyasa'}, to='leela', repo='rupaka')
    assert e.thread == e.id and len(e.id) == 12
    assert Envelope.load(e.dict()) == e and e.dict()['from']['name'] == 'abhyasa'

def test_post_logs_and_take_is_once(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_PEERS', str(tmp_path))
    d = peers_dir()
    post(d, 'claude-s2', Envelope('note', 'new shortcut', {'session': 's1'}))
    assert [e.text for e in take(d, 'claude-s2')] == ['new shortcut']
    assert take(d, 'claude-s2') == [] and len(read_log(d)) == 1

def test_take_filters_by_pred(tmp_path):
    post(tmp_path, 'k', a := Envelope('reply', 'r1', {}, thread='t1'))
    post(tmp_path, 'k', Envelope('note', 'n', {}))
    assert take(tmp_path, 'k', lambda e: e.thread == 't1') == [a]
    assert [e.text for e in take(tmp_path, 'k')] == ['n']

def test_take_is_once_under_threads(tmp_path):
    for i in range(50): post(tmp_path, 'k', Envelope('note', str(i), {}))
    with ThreadPoolExecutor(8) as ex: got = [e.id for r in ex.map(lambda _: take(tmp_path, 'k'), range(8)) for e in r]
    assert len(got) == 50 == len(set(got))

def test_wait_take_returns_when_posted(tmp_path):
    threading.Timer(.3, post, (tmp_path, 'k', Envelope('note', 'hi', {}))).start()
    assert [e.text for e in wait_take(tmp_path, 'k', 5, poll=.05)] == ['hi']
    assert wait_take(tmp_path, 'k', .2, poll=.05) == []

def test_peers_dir_from_cfg(tmp_path, monkeypatch):
    monkeypatch.delenv('RAMABANA_PEERS', raising=False)
    assert peers_dir(tmp_path) == tmp_path/'peers' and (tmp_path/'peers').is_dir()

def test_peers_dir_is_private(tmp_path, monkeypatch):
    monkeypatch.delenv('RAMABANA_PEERS', raising=False)
    assert peers_dir(tmp_path).stat().st_mode & 0o777 == 0o700


def torn(p): open(p, 'a').write('{"kind": "note", "te')


def test_torn_log_line_is_skipped(tmp_path):
    post(tmp_path, 'k', Envelope('note', 'a', {}))
    torn(tmp_path/'log.jsonl')
    assert [r['text'] for r in read_log(tmp_path)] == ['a']
    log(tmp_path, {'event': 'x', 'at': 9e9})
    assert [r.get('event') for r in read_log(tmp_path, 5e9)] == ['x'], 'the torn line is ended first, so the next row stays'
    post(tmp_path, 'k', Envelope('note', 'b', {}))
    assert [r['text'] for r in read_log(tmp_path) if 'text' in r] == ['a', 'b']
    assert (tmp_path/'hooks.log').read_text().count('log.jsonl') == 1, 'the file is named once'


def test_torn_inbox_line_does_not_stop_take(tmp_path):
    post(tmp_path, 'k', Envelope('note', 'a', {}))
    torn(tmp_path/'k.inbox.jsonl')
    assert [e.text for e in take(tmp_path, 'k')] == ['a']
    open(tmp_path/'k.inbox.jsonl', 'a').write('\n')
    post(tmp_path, 'k', Envelope('note', 'b', {}))
    assert [e.text for e in take(tmp_path, 'k')] == ['b']


def test_torn_pending_line_does_not_stop_held(tmp_path):
    ctl = SimpleNamespace(_pending=tmp_path/'r.pending.jsonl')
    ctl._pending.write_text(json.dumps(Envelope('ask', 'a', {}, id='a1').dict()) + '\n')
    torn(ctl._pending)
    assert [e.id for e in Control._held(ctl)] == ['a1']


def test_together_state_is_written_whole(tmp_path):
    st = together_on(tmp_path, 'k')
    assert together_state(tmp_path, 'k') == st and [p.name for p in tmp_path.iterdir()] == ['k.together.json']

def test_torn_line_does_not_take_the_next_row(tmp_path):
    (tmp_path/'log.jsonl').write_text('{"kind": "note", "te')
    log(tmp_path, {'event': 'after', 'at': 1.})
    assert [r['event'] for r in read_log(tmp_path)] == ['after']
    post(tmp_path, 'k', Envelope('note', 'hi', {}))
    (tmp_path/'k.inbox.jsonl').write_text((tmp_path/'k.inbox.jsonl').read_text() + '{"kind": "no')
    post(tmp_path, 'k', Envelope('note', 'again', {}))
    assert [e.text for e in take(tmp_path, 'k')] == ['hi', 'again']

def test_appends_from_threads_stay_whole(tmp_path):
    big = 'x' * 200_000   # bigger than one write, so rows would mix without the lock
    with ThreadPoolExecutor(8) as ex: list(ex.map(lambda i: log(tmp_path, {'n': i, 'pad': big, 'at': 1.}), range(64)))
    lines = (tmp_path/'log.jsonl').read_text().splitlines()
    assert len(lines) == 64 and sorted(json.loads(l)['n'] for l in lines) == list(range(64))
