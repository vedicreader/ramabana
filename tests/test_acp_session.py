"The ACP session's own bookkeeping, driven in-process: no subprocess, so it runs by default."
from ramabana.agent import Act
from ramabana.racp import Session


def _session():
    s = Session.__new__(Session)
    s.seen, s.gated, s.shell, s.sent = set(), {}, '', []
    s._send = s.sent.append
    s._body = lambda tool, args, preview: None
    return s

def _gate(s, id, tool='create_file', path='a.py'):
    "What `_permit` leaves behind: a pending call the editor was asked about."
    s.gated[(tool, path)] = id
    s.seen.add(id)

def _status(s, id): return [u.status for u in s.sent if getattr(u, 'tool_call_id', None) == id]


def test_a_sub_agent_read_is_not_its_own_tool_call():
    s = _session()
    kid = Act('view_file', {'path': 'a.py'}, parent_action_id='p1', run_id='run_x')
    s._act(kid); s._act(kid.finish('def a(): pass'))
    assert s.sent == [] and s.seen == set()


def test_an_approved_sub_agent_write_completes_its_gated_call_and_lets_it_go():
    s = _session()
    _gate(s, 'g1')
    kid = Act('create_file', {'path': 'a.py', 'text': 'x'}, parent_action_id='p1', run_id='run_x')
    s._act(kid); s._act(kid.finish('created a.py'))
    assert _status(s, 'g1')[-1] == 'completed', 'the approved write is not left pending in the editor'
    assert s.gated == {}, 'and its id is not kept for a later call on the same path'
    root = Act('create_file', {'path': 'a.py', 'text': 'y'})
    before = _status(s, 'g1')
    s._act(root)
    assert _status(s, root.id) == ['in_progress'] and _status(s, 'g1') == before, 'a later root edit is a call of its own'
