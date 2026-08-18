"""Stopping a turn: who says it stopped, and what the model is left holding.

`Backend.cancel` used to swallow every failure and answer False, and `Agent.cancel` passed that
answer straight through. Since `cancel` was a litert-only method, Stop reported "not running" about
every hosted turn that was running, having already released the approval it was waiting on.
"""
from ramabana.testing import fake_agent


def test_stopping_says_whether_there_was_a_turn_to_stop():
    a, be = fake_agent(replies=['done'])
    assert a.cancel() is False, 'idle is the one time that answer is true'
    a.lock.acquire()
    try: assert a.cancel() is True
    finally: a.lock.release()


def test_the_stop_reaches_the_backend_rather_than_being_swallowed():
    a, be = fake_agent(replies=['done'])
    a.ask('hello')
    a.cancel()
    assert be.cancelled, 'the backend was never asked'


def _bare_backend(chat):
    "A `Backend` holding `chat`, to exercise `Backend.cancel` itself rather than a double\'s override."
    from ramabana.runtime import Backend
    from ramabana.testing import SPEC
    be = Backend(SPEC)
    be.chat = chat
    return be


def test_a_backend_with_no_chat_reports_that_nothing_stopped():
    assert _bare_backend(None).cancel() is False


def test_a_backend_whose_chat_cannot_be_stopped_says_so_instead_of_lying():
    "The one case worth answering False for, and it is worth a problem the user can read."
    class NoCancel: pass
    be = _bare_backend(NoCancel())
    assert be.cancel() is False
    assert any('cannot be stopped' in p for p in be.problems)


def test_a_backend_forwards_the_stop_to_a_chat_that_has_one():
    class Chat:
        stopped = False
        def cancel(self): Chat.stopped = True
    be = _bare_backend(Chat())
    assert be.cancel() is True and Chat.stopped


def test_stopping_releases_whatever_the_turn_was_waiting_on():
    "A stop that leaves a worker parked on an approval has not stopped anything."
    import threading, time
    from ramabana import agent
    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    a, _ = fake_agent(replies=['done'], approvals=ap)
    threading.Thread(target=lambda: (time.sleep(0.05), a.cancel()), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'x'}}})
    stop()
    assert not d and 'stopped' in d.reply()
