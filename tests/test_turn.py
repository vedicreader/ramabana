"""One turn: what it did, what it cost, what streamed out of it, and what it can be forked into.

The activity feed and the usage counters are what a person reads a turn through, so most of this
block is about whether they tell the truth -- a tool that claimed success and changed nothing must
not appear in the diff, and a backend that counts cumulatively must not charge turn one twice.
"""
from dataclasses import replace

from ramabana import runtime
from ramabana.core import ModelSpec
from ramabana.runtime import Usage
from ramabana.testing import MemHost, fake_agent


def test_a_turn_records_its_activity_and_is_charged_exactly_once():
    "A backend counts cumulatively, so adding its total every turn charges turn one twice."
    a, be = fake_agent(replies=['done'])
    assert a.ask('hello') == 'done'
    assert a.use.total == 15 and be.sent and 'hello' in str(be.sent[0])

    b, bbe = fake_agent(replies=['one', 'two', 'three'])
    for p in ('a', 'b', 'c'): b.ask(p)
    assert bbe.use.total == 45          # the backend's running total after three sends
    assert b.turn_use.total == 15       # this turn only
    assert b.use.total == 45            # the session, not 15 + 30 + 45

    c, _ = fake_agent(replies=['fine'])
    c.ask('ok')
    assert c.turn_use.total == 15
    c._prepare('next')
    assert c.turn_use.total == 0, 'a failed turn inherited the last one\'s cost'

    u = Usage(model='a', input=1, output=2, total=3, cost=0.5) + Usage(model='b', input=1, output=1, total=2, cost=0.25)
    assert (u.total, u.cost, u.model) == (5, 0.75, 'b') and '$0.75' in repr(u)


def test_the_real_shell_tool_snapshots_and_settles_around_itself():
    "End to end through the wrapped tool: nothing has to call the two halves by hand."
    host = MemHost({'/proj/a.py': 'a = 1\n', '/proj/elsewhere.py': 'e = 1\n'})
    a, _ = fake_agent(host)
    a.before.clear()
    shell = next(t for t in a.tools if t.__name__ == 'run_shell')
    def ran(command, cwd=None, timeout=120):
        host.files['/proj/a.py'] = 'a = 2\n'
        return 0, 'done'
    host.run_cmd = ran
    shell('touch a.py')
    host.files['/proj/elsewhere.py'] = 'e = 2\n'         # after the command, before the turn ends
    assert a.changes() == {'/proj/a.py': ('a = 1\n', 'a = 2\n')}

def test_a_tree_too_big_to_watch_is_read_once_not_on_every_command(monkeypatch):
    "Over the cap every `run_shell` re-read the whole tree, then gave up: seconds a call for nothing."
    from ramabana import agent as A
    monkeypatch.setattr(A, 'SHELL_SNAPSHOT', 10)
    host = MemHost({'/proj/a.py': 'a = 1\n' * 5})
    a, _ = fake_agent(host)
    reads = []
    real = host.text_at
    host.text_at = lambda p: (reads.append(p), real(p))[1]
    assert a.snapshot_tree() is False
    n = len(reads)
    assert n and a.snapshot_tree() is False and len(reads) == n, 'the second command re-read the tree'


def test_an_attached_image_survives_the_tool_plan():
    """`compose` returns a list of content parts when an image is attached, and `list += str` extends
    it one character at a time -- so the plan, the preflight evidence and any requested skill used to
    arrive as several hundred single-character parts."""
    a, be = fake_agent(replies=['a screenshot of a traceback'])
    a.local_multimodal = True
    # a window a model that can see actually has: `SPEC` is 1k, and one picture is priced
    # at `IMG_TOKENS` however small its bytes are, so the fit check would reject the turn
    be.spec = replace(be.spec, ctx=128_000)
    a.ask(a.compose('what is in this image? /grep Traceback', image=b'\x89PNG-not-really'))   # a named tool brings a plan
    sent = be.sent[-1]
    assert isinstance(sent, list) and len(sent) == 2
    assert sent[0] == b'\x89PNG-not-really'
    assert '<user-request>' in sent[1] and '<tool-plan' in sent[1]


def test_a_tool_call_written_as_prose_earns_one_reminder():
    """The tags channel asks the model to punctuate exactly, and a smaller model sometimes narrates
    the call instead of emitting it. That was reported and then dropped, so the turn simply did not
    do the thing. One corrective turn asks for the call again -- appended, never a re-run, because a
    stream cannot unsay what already reached the screen.
    """
    sent = []

    class Sloppy(runtime.RishiBackend):
        def _start(self): return object()
        def _usage(self): return None
        def _stream(self, msg, **kw):
            sent.append(msg)
            yield "I'll search now: <tool_call> search_code(query='rrf')" if len(sent) == 1 else 'done'

    spec = ModelSpec('claude/claude-sonnet-4-6', 'claude', 'claude-sonnet-4-6', 128_000)
    b = Sloppy(spec, tools=[lambda: None])
    out = ''.join(b.stream('find rrf'))

    assert len(sent) == 2, f'{len(sent)} turns; the reminder never went'
    assert runtime.TAG_REMINDER in str(sent[1]), sent[1]
    assert 'done' in out, out
    assert any('prose' in p for p in b.problems), b.problems

    # and only one: a model that keeps narrating must not loop
    sent.clear()
    class Always(Sloppy):
        def _stream(self, msg, **kw):
            sent.append(msg); yield '<tool_call> nope'
    b2 = Always(spec, tools=[lambda: None])
    ''.join(b2.stream('again'))
    assert len(sent) == 2, f'{len(sent)} turns; the reminder repeated'
