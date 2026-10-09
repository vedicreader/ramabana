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


# -- what a resume puts back -------------------------------------------------------------

MODEL = 'gpt-mini'   # a registered name: `resume_session` puts the session's model back


def restore(a, rows_):
    """Put `rows_` on disk and read them back, because the log is what a resume rebuilds from.

    Setting `a.history` was enough while every route read it. They read the session index now, so
    a row that never reached the log is a row a resume cannot see -- which is the contract this
    file is about."""
    a.history_path.write_text('\n'.join(json.dumps(r) for r in rows_) + '\n')
    a.rebuild_index(force=True)
    a.refresh_history()


def _replayed(a, rows_):
    "The messages a resume puts back, from rows this session really wrote."
    restore(a, [dict(r, model=MODEL) for r in rows_])
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


# -- what the review found the first cut had broken ---------------------------------------

def test_a_stopped_turn_gets_its_own_id_and_not_the_last_turns(agent):
    """A row written before `_prepare` inherited the previous turn's id, usage and activity. Two
    rows sharing an id collide in `conversation_parts`, where a group name is built from it."""
    list(agent.stream('turn one'))
    list(agent.stream('turn two, stopped', on_registered=lambda run: run.request_cancel()))
    got = rows(agent)
    assert len({r['turn_id'] for r in got}) == 2, 'the stopped turn reused the last turn id'
    assert got[1]['usage']['total'] == 0, "it inherited the previous turn's cost"
    assert got[1]['activity'] == [], "it inherited the previous turn's activity"


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
