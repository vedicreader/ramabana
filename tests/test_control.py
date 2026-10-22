"A prompt sent while a turn runs waits its turn, and the worker that ran the first runs it."
import tempfile, time
from pathlib import Path

from ramabana.control import Control, control_call
from ramabana.testing import FakeBackend, fake_agent


class Slow(FakeBackend):
    def _send(self, msg, **kw):
        time.sleep(.3)
        return super()._send(msg, **kw)


def test_a_prompt_sent_during_a_turn_is_queued_then_run_in_order():
    d = Path(tempfile.mkdtemp(dir='/tmp'))
    a, _ = fake_agent(cfg=d)
    be = Slow(replies=['one done', 'two done'])
    a._be = a._be_or_none = lambda job='turn': be
    ctl = Control(a).start()
    try:
        assert control_call(ctl.path, 'prompt', text='one') == {'started': True}
        assert control_call(ctl.path, 'prompt', text='two') == {'queued': 1}
        for _ in range(300):
            if not control_call(ctl.path, 'status')['running']: break
            time.sleep(.01)
        st = control_call(ctl.path, 'status')
        assert st['last']['reply'] == 'two done' and st['queued'] == 0
        assert ['one' in str(m) for m in be.sent] == [True, False] and 'two' in str(be.sent[1])
    finally:
        ctl.close(); a.close()


def test_a_failing_turn_never_stalls_the_runner_and_cancel_drops_the_queue():
    d = Path(tempfile.mkdtemp(dir='/tmp'))
    a, _ = fake_agent(cfg=d)
    be = Slow(replies=['ok', 'ok', 'ok'])
    a._be = a._be_or_none = lambda job='turn': be
    real = a.ask
    a.ask = lambda text, **kw: (_ for _ in ()).throw(RuntimeError('the model is gone')) if text == 'boom' else real(text, **kw)
    ctl = Control(a).start()
    try:
        control_call(ctl.path, 'prompt', text='boom')
        for _ in range(300):
            if not control_call(ctl.path, 'status')['running']: break
            time.sleep(.01)
        st = control_call(ctl.path, 'status')
        assert not st['running'] and st['last']['state'] == 'failed' and 'gone' in st['last']['error']
        assert control_call(ctl.path, 'prompt', text='one') == {'started': True}, 'the next prompt starts a turn'
        control_call(ctl.path, 'prompt', text='two'); control_call(ctl.path, 'prompt', text='three')
        assert control_call(ctl.path, 'cancel')['dropped'] == 2 and not a.queued
    finally:
        ctl.close(); a.close()


def test_events_after_a_rollover_start_again_and_start_never_steals_a_socket(tmp_path):
    import socket
    d = Path(tempfile.mkdtemp(dir='/tmp'))
    a, _ = fake_agent(cfg=d)
    log = a.events_to(d/'job.events', max_bytes=600)
    ctl = Control(a).start()
    try:
        for i in range(3): a._heard_steer([f'line {i}'])
        first = control_call(ctl.path, 'events')
        for i in range(12): a._heard_steer([f'more {i} ' + 'x' * 40])
        again = control_call(ctl.path, 'events', offset=first['offset'] + 10_000)
        assert again['rotated'] and again['events'], 'a page past the end reads the new file from its start'
        try: Control(a, path=ctl.path).start()
        except RuntimeError: pass
        else: raise AssertionError('a live runner keeps its socket')
        plain = d/'plain.txt'; plain.write_text('keep me')
        try: Control(a, path=plain).start()
        except RuntimeError: assert plain.read_text() == 'keep me'
        else: raise AssertionError('a file that is not a socket is never removed')
    finally:
        ctl.close()
    stale = d/'stale.sock'
    s = socket.socket(socket.AF_UNIX); s.bind(str(stale)); s.close()   # what a crashed runner leaves
    revived = Control(a, path=stale).start()
    assert control_call(revived.path, 'status')['running'] is False
    revived.close(); a.close()
