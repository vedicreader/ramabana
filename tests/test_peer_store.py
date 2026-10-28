"The peers store: the envelope, the log and the inboxes."
import threading
from concurrent.futures import ThreadPoolExecutor

from ramabana.peers import Envelope, peers_dir, post, read_log, take, wait_take


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
