"""A turn that was stopped is still a turn that happened.

A cancelled turn, and one whose stream is abandoned, used to write nothing. The prompt and every
chunk already streamed were lost, so the conversation could not be found again after a restart.
The rule existed because `resume_session` rebuilds model context from the log and a half-streamed
reply would go back as a complete one. That is a reason to keep a stopped turn out of the context,
not out of the record, and `state` is what separates the two.
"""
import json
import tempfile
from pathlib import Path

import pytest

from ramabana.agent import REPLAYED
from ramabana.testing import fake_agent


@pytest.fixture
def agent():
    a, _ = fake_agent(cfg=Path(tempfile.mkdtemp()))
    return a


def rows(a):
    "Every row on disk, which is what survives a restart. Not `a.history`, which does not."
    p = a.history_path
    return [json.loads(l) for l in p.read_text().splitlines()] if p is not None and p.exists() else []


def test_a_turn_abandoned_after_one_chunk_is_recorded_with_what_it_streamed():
    """A caller that stops iterating drops the generator, which raises `GeneratorExit`. That
    derives from `BaseException`, so `except Exception` never saw it and no handler ran at all."""
    a, _ = fake_agent(cfg=Path(tempfile.mkdtemp()))
    g = a.stream('what colour is the sky?')
    chunk = next(g)
    g.close()

    got = rows(a)
    assert len(got) == 1, 'the abandoned turn wrote nothing'
    assert got[0]['state'] == 'abandoned'
    assert got[0]['prompt'] == 'what colour is the sky?'
    assert got[0]['reply'] == chunk, 'the chunk it had already streamed was lost'


def test_an_abandoned_turn_does_not_leave_the_agent_busy(agent):
    """No handler ran on the abandoned path, so `run.finish` was never reached either. The run
    stayed live, and `busy` blocks `/resume`, `/model` and the next turn for the whole session."""
    g = agent.stream('dropped')
    next(g)
    g.close()
    assert agent.busy is False, 'the dropped turn left the agent working forever'
    agent.stream('and another one after it').close()   # which would raise if a run were still live


def test_a_turn_cancelled_mid_stream_is_recorded(agent):
    g = agent.stream('a long question')
    next(g)
    for r in agent.runs(active=True): agent.cancel(r['id'])
    list(g)

    got = rows(agent)
    assert len(got) == 1
    assert got[0]['state'] == 'cancelled'
    assert got[0]['prompt'] == 'a long question'


def test_a_turn_cancelled_before_it_starts_is_recorded_with_no_reply(agent):
    def stop(run): run.request_cancel()
    list(agent.stream('stopped at once', on_registered=stop))

    got = rows(agent)
    assert len(got) == 1
    assert got[0]['state'] == 'cancelled'
    assert got[0]['reply'] == ''


def test_a_turn_that_completes_is_recorded_once_and_not_twice(agent):
    list(agent.stream('one question'))
    got = rows(agent)
    assert len(got) == 1, f'{len(got)} rows for one turn'
    assert got[0]['state'] == 'complete'


def test_ask_records_a_cancelled_turn_too(agent):
    """`ask` had the same silent returns as `stream`. Cancelled from inside `send`, so the path is
    reached every run rather than whenever a timer happens to win."""
    be = agent._be('turn')
    real = be.send

    def send(msg, run=None, **kw):
        run.request_cancel()
        return real(msg, run=run, **kw)

    be.send = send
    agent.ask('a question that is stopped')
    got = rows(agent)
    assert len(got) == 1, 'ask wrote nothing for a cancelled turn'
    assert got[0]['state'] == 'cancelled'
    assert got[0]['prompt'] == 'a question that is stopped'


def test_ask_records_a_completed_turn_once(agent):
    agent.ask('one question')
    got = rows(agent)
    assert len(got) == 1
    assert got[0]['state'] == 'complete'


# -- what a resume puts back -------------------------------------------------------------

MODEL = 'gpt-mini'   # a registered name: `resume_session` puts the session's model back


def test_only_a_complete_or_failed_turn_goes_back_as_model_context(tmp_path):
    "Not the constant: what a resume actually puts back for each state a row can carry."
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('kept'))
    base = rows(a)[0]
    for state, wanted in [('complete', True), ('failed', True),
                          ('cancelled', False), ('abandoned', False)]:
        back = ' '.join(_replayed(a, [dict(base, state=state, prompt=f'a {state} turn')]))
        assert (f'a {state} turn' in back) is wanted, f'{state} replayed={not wanted}'


def _replayed(a, rows_):
    "The messages a resume puts back, from rows this session really wrote."
    a.history = [dict(r, model=MODEL) for r in rows_]
    a.resume_session(a.session_id)
    # a turn has already built a chat, so the resume restores into it rather than stashing
    b = a._be('turn')
    return [m.get('content', '') for m in (b._resume_hist or b.hist or [])]


def test_a_stopped_turn_is_in_the_log_and_not_in_the_replayed_context(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('the one that finished'))
    g = a.stream('the one that was dropped')
    next(g)
    g.close()

    got = rows(a)
    assert [r['state'] for r in got] == ['complete', 'abandoned'], 'both turns should be recorded'
    back = ' '.join(_replayed(a, got))
    assert 'the one that finished' in back
    assert 'the one that was dropped' not in back, 'a fragment went back as a whole turn'


def test_a_resume_builds_the_same_context_as_one_with_the_stopped_row_deleted(tmp_path):
    "The context a resume builds is unchanged for every log that already exists."
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('kept'))
    g = a.stream('dropped')
    next(g)
    g.close()
    got = rows(a)

    with_stopped = _replayed(a, got)
    without = _replayed(a, [r for r in got if r['state'] in REPLAYED])
    assert with_stopped == without


def test_a_row_written_before_state_existed_is_still_replayed(tmp_path):
    "An old log has no `state`. It must keep reading as a complete turn."
    a, _ = fake_agent(cfg=tmp_path)
    list(a.stream('an older turn'))
    old = [{k: v for k, v in r.items() if k != 'state'} for r in rows(a)]
    assert all('state' not in r for r in old)

    back = ' '.join(_replayed(a, old))
    assert 'an older turn' in back, 'a row with no state stopped being replayed'


def test_a_stopped_turn_still_counts_in_the_session_listing(agent):
    "It is a turn that happened, so a picker should show it."
    g = agent.stream('dropped')
    next(g)
    g.close()
    picked = [s for s in agent.sessions() if s['id'] == agent.session_id]
    assert picked and picked[0]['turns'] == 1


# -- what the review found the first cut had broken ---------------------------------------

def test_a_turn_whose_finish_raises_still_leaves_one_row(agent):
    """`keep` marked the row written before writing it, so a `_finish` failure wrote nothing at
    all. That is one row fewer than before stopped turns were recorded."""
    agent._finish = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('boom'))
    list(agent.stream('the finish blows up'))
    got = rows(agent)
    assert len(got) == 1, 'a failing turn left no trace'
    assert got[0]['state'] == 'failed'
    assert 'boom' in got[0]['error']


def test_a_row_that_could_not_be_written_is_tried_again(agent):
    "The flag is set by a write that happened, so a failed write does not consume the one chance."
    tries = []
    real = agent._remember

    def flaky(prompt, text, error='', state='complete'):
        tries.append(state)
        if len(tries) == 1: raise RuntimeError('the disk was busy')
        return real(prompt, text, error, state=state)

    agent._remember = flaky
    list(agent.stream('written on the second attempt'))
    assert len(tries) > 1, 'the failed write consumed the only attempt'
    assert len(rows(agent)) == 1


def test_a_stopped_turn_gets_its_own_id_and_not_the_last_turns(agent):
    """A row written before `_prepare` inherited the previous turn's id, usage and activity. Two
    rows sharing an id collide in `conversation_parts`, where a group name is built from it."""
    list(agent.stream('turn one'))
    list(agent.stream('turn two, stopped', on_registered=lambda run: run.request_cancel()))
    got = rows(agent)
    assert len({r['turn_id'] for r in got}) == 2, 'the stopped turn reused the last turn id'
    assert got[1]['usage']['total'] == 0, "it inherited the previous turn's cost"
    assert got[1]['activity'] == [], "it inherited the previous turn's activity"


def test_a_turn_cancelled_before_its_backend_starts_is_recorded(agent):
    "`run.start` returning False sat outside the try, so the `finally` never saw it."
    from ramabana.agent import Agent
    started = Agent.start
    agent.start = lambda: (agent.run().request_cancel(), started(agent))[1]
    list(agent.stream('cancelled while the backend was building'))
    got = rows(agent)
    assert len(got) == 1
    assert got[0]['state'] == 'cancelled'


def test_an_abandoned_turn_leaves_a_live_child_run_alone(agent):
    """`detach` marked every child terminal without stopping any of them, so `busy` read idle
    while a delegated sub-agent was still running and a resume could swap history under it."""
    g = agent.stream('a turn with a delegation under it')
    next(g)
    child = agent.run().child('a delegated question')
    child.start()
    g.close()

    assert child.state == 'running', 'the child was marked terminal without being stopped'
    assert agent.busy is True, 'the agent read idle while a child was still working'
    child.finish()
    assert agent.busy is False


def test_a_stopped_turn_is_not_offered_for_reshaping(agent):
    "`compile_conversation` writes straight into the live chat, so it needs the same filter."
    list(agent.stream('the one that finished'))
    g = agent.stream('the one that was dropped')
    next(g)
    g.close()
    parts = agent.conversation_parts()
    assert not any('dropped' in p['text'] for p in parts), 'a fragment reached the reshape surface'
    assert len({p['group'] for p in parts}) == len(parts), 'two rows produced colliding group ids'


def test_a_stopped_turn_does_not_widen_the_folder_boundary_on_a_resume(agent):
    "Honouring a root from a turn whose context is left out opens a folder nobody agreed to."
    list(agent.stream('opened a folder'))
    got = rows(agent)
    act = [{'tool': 'add_root', 'args': {'path': '/somewhere/else'}, 'ok': True}]
    agent.history = [dict(got[0], state='abandoned', activity=act)]
    assert agent.session_added_roots(agent.session_id) == []
    agent.history = [dict(got[0], state='complete', activity=act)]
    assert agent.session_added_roots(agent.session_id) == ['/somewhere/else']
