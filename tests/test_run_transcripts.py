"""A run keeps a transcript a person can tail, and a person can talk back to the sub-agent working it."""

import json

from ramabana.monitor import Monitors
from ramabana.runtime import Run
from ramabana.testing import FakeBackend, MemHost, fake_agent
from ramabana.tools import _inboxed, delegate


def view(path: str) -> str:
    "the file"
    return 'contents'


def test_a_message_told_to_a_run_reaches_the_sub_agent_and_its_transcript(tmp_path):
    be, run = FakeBackend(), Run('run_t', 'child', 'q', 'm', log=tmp_path/'run_t.log')
    run.tell('also check b')
    assert delegate(be, 'q', [view], run=run) == '(done)'
    assert be.spawned[0].sent == ['q', 'also check b'], 'the queued message became a follow-up turn'
    log = run.log.read_text()
    assert 'question: q' in log and 'user: also check b' in log and 'answer:' in log
    out = _inboxed(view, run)
    assert out('a.py') == 'contents'
    run.tell('and c')
    assert f'<user-message key="{run.key}">\nand c\n</user-message>' in out('a.py')
    assert run.drain_inbox() == []


def test_tell_and_watch_answer_in_text_when_there_is_no_run_or_no_tmux(tmp_path):
    a, be = fake_agent(cfg=tmp_path)
    assert 'no run named' in a.command('/tell run_nope hi')
    a.ask('hello')
    rid = a.runs()[-1]['id']
    assert 'finished' in a.tell(rid, 'late')
    assert (tmp_path/'runs'/a.session_id/f'{rid}.log').read_text().count('\n') >= 2
    assert a.command('/watch') == 'nothing is running or watched'
    a.monitors.add('/proj', 'say what moved')
    assert 'watching' in a.command('/watch') and '/proj' in a.command('/watch')
    out = a.command('/watch monitors')
    assert 'no tmux here' in out and 'tail -n 200 -f' in out and a.monitors.log.exists()
    assert a.unwatch() == 'nothing was being watched'
    assert {'tell', 'watch', 'unwatch'} <= set(a.commands())


def test_a_folder_review_runs_under_a_run_with_its_own_transcript(tmp_path):
    h, be = MemHost({'/proj/a.py': 'one\n'}), FakeBackend()
    m = Monitors(h, get_backend=lambda: be, get_tools=lambda: [view], log_dir=lambda: tmp_path)
    m.add('/proj', 'say what moved')
    h.write('/proj/a.py', 'ONE\n')
    rec, = m.check(force=True)
    assert rec['review'] == 'sub answer' and rec['run_id'] in m.runs
    assert json.loads(m.log.read_text().splitlines()[-1])['run_id'] == rec['run_id']
    assert 'answer: sub answer' in (tmp_path/f"{rec['run_id']}.log").read_text()
    assert m.runs[rec['run_id']].terminal
