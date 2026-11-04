"""`Agent.ask(deadline=, stop=)` and `Agent.halt()`: an app stops a long turn and its sub-agents without a watchdog of its own.

abhyasa's research ran a thread that polled an Event every 0.5 s, then cancelled the turn and walked the private `_side_runs`.
"""
import threading, time

from ramabana.testing import FakeBackend, fake_agent


class Busy(FakeBackend):
    "A turn that works until it is cancelled. With `sub`, it starts a sub-agent run first."
    def __init__(self, *a, sub=None, **kw):
        super().__init__(*a, **kw)
        self.sub, self.started = sub, threading.Event()
    def _send(self, msg, **kw):
        if self.sub is not None: self.sub(self)
        self.started.set()
        for _ in range(500):
            if self.cancelled: return ''
            time.sleep(.01)
        return 'finished'


def busy(sub=None):
    a, _ = fake_agent()
    b = Busy(sub=sub)
    a._be = a._be_or_none = lambda job='turn': b
    return a, b


def test_halt_on_an_idle_agent_stops_nothing():
    a, _ = fake_agent()
    assert a.halt() == 0


def test_a_deadline_cancels_a_slow_turn():
    a, b = busy()
    t = time.monotonic()
    r = a.ask('work', deadline=.3, result=True)
    assert r.state == 'cancelled' and b.cancelled
    assert time.monotonic() - t < 3


def test_stop_reaches_the_sub_agents():
    kids = []
    def sub(b):
        run = a.run()
        kid = run.child('find a source')
        kid.start(FakeBackend())
        run.children.append(kid); kids.append(kid)
    a, b = busy(sub)
    stop = threading.Event()
    threading.Thread(target=lambda: b.started.wait(5) and stop.set()).start()
    r = a.ask('work', stop=stop, result=True)
    assert r.state == 'cancelled'
    assert kids and kids[0].cancelled and kids[0].backend.cancelled, 'the sub-agent run and its backend were stopped too'


def test_halt_counts_the_runs_it_stopped():
    a, b = busy()
    out = []
    t = threading.Thread(target=lambda: out.append(a.ask('work', result=True)))
    t.start(); b.started.wait(5)
    assert a.halt() == 1
    t.join(5)
    assert out[0].state == 'cancelled' and a.halt() == 0


def test_no_deadline_and_no_stop_is_the_plain_turn():
    a, _ = fake_agent(replies=['hello'])
    assert a.ask('hi') == 'hello'


def test_cancel_returns_the_run_state():
    "One `cancel` only: the registered-run one, which returns a dict."
    a, _ = fake_agent()
    assert a.cancel() == {'id': None, 'state': 'idle', 'children': []}
