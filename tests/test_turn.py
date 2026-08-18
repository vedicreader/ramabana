"""One turn: what it did, what it cost, what streamed out of it, and what it can be forked into.

The activity feed and the usage counters are what a person reads a turn through, so most of this
block is about whether they tell the truth -- a tool that claimed success and changed nothing must
not appear in the diff, and a backend that counts cumulatively must not charge turn one twice.
"""
from dataclasses import replace

from ramabana import agent, core
from ramabana.runtime import Usage
from ramabana.testing import MemHost, ScriptedBackend, Step, fake_agent


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


def test_the_activity_feed_reads_like_what_a_person_would_say():
    """Showing a spinner while a fetch happens is the difference between looking alive and looking
    stuck, so an act is recorded when it starts and not only when it ends. `run_shell` is the tool a
    person most wants to read back, and it had no summary at all. A fence inside a result must not
    end the fold that contains it.
    """
    s = agent.summarise
    assert s('search_code', {'query': 'AgentSession'}) == 'Search AgentSession'
    assert s('view_file', {'path': 'leela/ai.py', 'start': 240, 'end': 290}) == 'View leela/ai.py:240-290'
    assert s('read_url', {'url': 'https://github.com/AnswerDotAI/ipymini'}).startswith('Web fetch: https://')
    assert s('edit_file', {'path': 'a.py'}) == 'Edit a.py'
    assert s('run_shell', {'command': 'pytest -q'}) == 'Run pytest -q'
    assert s('grep', {'pattern': 'RESERVE', 'path_filter': 'tests/'}) == 'Grep RESERVE in tests/'
    assert s('list_watches', {'due_only': False}) == 'List watches'
    assert agent.Act(tool='run_shell').kind == 'run'

    seen = []
    act = agent.Activity(on_change=lambda a: seen.append((a.summary, a.done)))
    one = act.start('read_url', {'url': 'https://x'})
    act.finish(one, 'the page')
    assert [d for _, d in seen] == [False, True]
    assert one.detail == 'the page' and one.done

    feed = agent.Activity()
    feed.mark()
    feed.finish(feed.start('search_code', {'query': 'q'}), 'a hit')
    md = feed.md(mark=0)
    assert '<details>' in md and 'Search q' in md and 'a hit' in md

    fenced = agent.Activity()
    f = fenced.start('view_file', {'path': 'a.md'})
    fenced.finish(f, 'text\n```\nfenced\n```\n')
    assert '\n```\n' not in f.md().split('```\n', 1)[1].rsplit('```', 1)[0]


def test_wrapping_a_tool_keeps_the_schema_the_model_reads():
    """Both backends build their tool schema from the signature and docstring, so the recorder must
    be transparent to `inspect` -- or every tool arrives as `(*args, **kw)` with no documentation."""
    import inspect
    a, _ = fake_agent()
    t = next(t for t in a.tools if t.__name__ == 'view_file')
    assert t.__doc__ and 'lineno|hash|content' in t.__doc__
    assert list(inspect.signature(t).parameters) == ['path', 'start', 'end']


def test_changes_report_the_file_not_the_claim():
    "A tool that reported success and changed nothing must not appear in the diff."
    a, _ = fake_agent(MemHost({'/proj/a.py': 'x = 1\n'}))
    create = next(t for t in a.tools if t.__name__ == 'create_file')
    a.before.clear()
    create(path='/proj/a.py', text='x = 1\n')          # writes the same bytes back
    assert a.changes() == {}
    create(path='/proj/a.py', text='x = 2\n')
    assert a.changes() == {'/proj/a.py': ('x = 1\n', 'x = 2\n')}


def test_streaming_yields_as_it_goes_and_composes_the_same_message_as_blocking():
    """A stream that only yields at the end is a blocking call with extra steps, and a streamed turn
    that quietly saw a different message would be a very hard bug to find."""
    be = ScriptedBackend(steps=[Step(text='one two three')], token_delay=0)
    be.start()
    got = list(be.stream('hi'))
    assert len(got) == 3 and ''.join(got).split() == ['one', 'two', 'three']

    a, abe = fake_agent(replies=['x', 'y'])
    a.ask_with('q', context='CTX', screen='SCR')
    blocking = str(abe.sent[-1])
    list(a.stream_with('q', context='CTX', screen='SCR'))
    assert str(abe.sent[-1]) == blocking
    assert '<notebook>' in blocking and '<screen>' in blocking

    b, _ = fake_agent(replies=['all done'])
    assert ''.join(b.stream('go')).strip() == 'all done'
    assert b.use.total == 15


def test_reasoning_effort_is_applied_to_the_chat_not_passed_to_the_call():
    from ramabana.runtime import RishiBackend
    be = RishiBackend(core.ModelSpec('cloud', 'remote', 'openai/gpt-test', ctx=1000))

    class Chat:
        reasoning_effort = None
        def __call__(self, msg, **kw):
            assert 'reasoning_effort' not in kw
            return {'content': [{'type': 'text', 'text': 'ok'}]}

    be.chat = Chat()
    assert be._send('hello', reasoning_effort='high') == 'ok'
    assert be.chat.reasoning_effort == 'high'


def test_turns_have_stable_ids_and_fork_into_a_bounded_set_of_checkpoints():
    "Each checkpoint is a deep copy of a whole conversation, so an unbounded dict of them is a leak."
    a, be = fake_agent(replies=['first answer', 'branch answer'])
    assert a.ask('first question') == 'first answer'
    turn_id = a.history[-1]['turn_id']
    assert turn_id and a.history[-1]['branch_id'] == 'main'
    branch = a.revise(turn_id, 'user authored answer')
    assert branch['branch_id'].startswith('branch_')
    assert be.hist[-1]['content'] == 'user authored answer'
    assert a.ask('continue from revision') == 'branch answer'
    assert a.history[-1]['branch_id'] == branch['branch_id']

    b, _ = fake_agent(replies=['ok'] * 30)
    for i in range(agent.MAX_CHECKPOINTS + 5): b.ask(f'turn {i}')
    assert len(b.checkpoints) == agent.MAX_CHECKPOINTS
    assert b.current_turn_id in b.checkpoints


def test_an_attached_image_survives_the_tool_plan():
    """`compose` returns a list of content parts when an image is attached, and `list += str` extends
    it one character at a time -- so the plan, the preflight evidence and any requested skill used to
    arrive as several hundred single-character parts."""
    a, be = fake_agent(replies=['a screenshot of a traceback'])
    a.local_multimodal = True
    # a window a model that can see actually has: `SPEC` is 1k, and one picture is priced
    # at `IMG_TOKENS` however small its bytes are, so the fit check would reject the turn
    be.spec = replace(be.spec, ctx=128_000)
    a.ask(a.compose('what is in this image?', image=b'\x89PNG-not-really'))
    sent = be.sent[-1]
    assert isinstance(sent, list) and len(sent) == 2
    assert sent[0] == b'\x89PNG-not-really'
    assert '<user-request>' in sent[1] and '<tool-plan' in sent[1]
