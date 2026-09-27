"""The seams a non-terminal frontend needs: approval decisions, mode switches, command expansion, watch and background callbacks, the verify text."""
from ramabana.agent import APPROVE_MODES, Approvals
from ramabana.testing import MemHost, fake_agent

from test_briefing_and_rewind import PY, _turn_that_wrote


def test_decide_answers_what_needs_no_person_and_set_mode_settles_the_rest():
    ap = Approvals(tools={'edit_file', 'run_shell'}, mode='edits')
    assert ap.decide('edit_file', {'path': 'a.py'}).answer is True
    assert ap.decide('list_files', {}).answer is True
    assert ap.decide('run_shell', {'command': 'ls'}) is None and len(ap.history) == 3
    assert ap.set_mode('yolo') == f"usage: /approve [{'|'.join(APPROVE_MODES)}]"
    assert ap.set_mode('edits') == 'approvals: edits'
    assert ap.set_mode('off') == 'approvals: edits -> off' and ap.decide('edit_file', {'path': 'a.py'}).answer is False


def test_the_verify_text_is_kept_and_streamed():
    host = MemHost({'/proj/a.py': 'def a(): pass\n', '/proj/pyproject.toml': PY}, commands={'pytest -q': (0, '3 passed')})
    a, _ = fake_agent(host, replies=['done'])
    _turn_that_wrote(a, host)
    a._finish('done')
    assert a.last_verify.startswith('verify (pytest -q)') and '3 passed' in a.last_verify
    prep = a._prepare
    def prep_and_write(p):
        out = prep(p)
        a.before['/proj/a.py'], host.files['/proj/a.py'] = host.files['/proj/a.py'], 'def a(): return 2\n'
        return out
    a._prepare = prep_and_write
    out = ''.join(a.stream('again'))
    assert 'done' in out and 'verify (pytest -q)' in out
    a._finish('quiet')
    assert a.last_verify == ''
