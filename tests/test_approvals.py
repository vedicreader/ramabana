"""The approval gate: which calls are put to a person, and what comes back when they say no.

The point of the whole module is the reason, not the refusal. "Denied" teaches a model nothing and
gets retried; "that file is generated, edit the notebook instead" changes its approach. So every
test here is really about whether the reason survives the trip back.
"""
import threading
import time

from ramabana import agent
from ramabana.testing import fake_agent
from ramabana.tools import WRITE_TOOLS


def edit_call(path='a.py'): return {'function': {'name': 'edit_file', 'arguments': {'path': path}}}


def answer_when_asked(ap, ok, note=''):
    "Answer the next pending ask from another thread, the way a frontend does."
    def run():
        for _ in range(200):
            if (a := ap.pending) is not None: return ap.answer(a.id, ok, note)
            time.sleep(0.01)
    threading.Thread(target=run, daemon=True).start()


def test_the_gate_draws_its_line_around_the_write_tools_and_answers_as_a_bool():
    """Both engines call `approve(tc)` and branch on the result, so it has to be falsy when
    refused. The line is not only the filesystem: deleting a standing reminder and spending money
    in a trolley are both things a person should see before they happen. And a sub-agent nobody is
    watching gets none of them -- a delegated question is a question.
    """
    from ramabana.tools import GIT_READ_TOOLS, GIT_WRITE_TOOLS
    assert {'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
            'run_shell', 'memory_forget', 'create_skill', 'cancel_watch', 'cart_add',
            'cart_remove'} | GIT_WRITE_TOOLS == set(WRITE_TOOLS)
    assert not (set(GIT_READ_TOOLS) & set(WRITE_TOOLS)), 'rehearsing a merge is not approving one'

    ap = agent.Approvals(tools={'edit_file'}, mode='auto')
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})   # ungated
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': '{"path": "a.py"}'}})
    assert bool(d) and d.args == {'path': 'a.py'}                 # arguments parsed either shape

    from ramabana.tools import read_only
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS) and 'search_code' in names


def test_a_refusal_always_carries_a_reason_the_model_can_act_on():
    "And an approval carries one too, when the person had something to add to it."
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    answer_when_asked(ap, False, 'that file is generated, edit the notebook instead')
    d = ap.gate(edit_call('gen.py'))
    stop()
    assert not d and 'that file is generated' in d.reply()

    off = agent.Approvals(tools={'edit_file'}, mode='off')
    d2 = off.gate(edit_call())
    assert not d2 and agent.DENIED in d2.reply() and 'switched off' in d2.reply()

    auto = agent.Approvals(tools={'edit_file'}, mode='auto')
    assert auto.request('edit_file', {'path': 'a.py'}).reply() is None   # nothing to say
    assert agent.Ask(tool='edit_file').resolve(True, 'keep the docstring').reply(
        ).endswith('keep the docstring')


def test_a_refusal_nobody_could_be_asked_about_still_reaches_the_recorder():
    """Otherwise it surfaces as a bare tool failure with the explanation nowhere in the UI. And a
    blocked worker thread is a hung IDE, so refusing fast is a bad answer that is at least an
    answer -- as is a cancelled turn releasing whatever was waiting on it."""
    heard = []
    agent.Approvals(tools={'edit_file'}, mode='off', on_answer=heard.append).gate(edit_call())
    agent.Approvals(tools={'edit_file'}, on_answer=heard.append).gate(edit_call())  # none listening
    assert len(heard) == 2 and all(not a and a.note for a in heard)

    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate(edit_call())
    assert not d and time.time() - t0 < 1 and 'nothing is listening' in d.reply()

    live = agent.Approvals(tools={'edit_file'}, timeout=30)
    stop = live.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), live.cancel_all()), daemon=True).start()
    c = live.gate(edit_call())
    stop()
    assert not c and 'cancelled' in c.reply()


def test_every_watcher_and_the_recorder_hear_the_same_ask_with_a_preview():
    """A second frontend opening must not unhook the notebook recorder, or the first frontend. The
    preview is what makes an approval answerable: a hash address and a diff, not a tool name."""
    seen = []
    ap = agent.Approvals(tools={'edit_file'}, mode='auto', on_ask=lambda a: seen.append('recorder'))
    ap.listen(on_ask=lambda a: seen.append('one'))
    ap.listen(on_ask=lambda a: seen.append('two'))
    ap.mode = 'ask'
    answer_when_asked(ap, True)
    ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert sorted(seen) == ['one', 'recorder', 'two']

    p = agent.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = agent.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2

    # Hosted approvals reach rishi's own remote path now, so the shim is three functions saying so.
    assert agent.apply() and agent.apply() and agent.applied()
