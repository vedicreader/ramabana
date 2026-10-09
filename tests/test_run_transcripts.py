"""A run keeps a transcript a person can tail, and a person can talk back to the sub-agent working it."""

from ramabana.runtime import Run
from ramabana.testing import FakeBackend
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
