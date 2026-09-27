"""`Session._after_text`: the real before/after an `edit_file` or `replace_text` call would leave,
so the editor can render a native diff instead of exhash command text or a raw preview. Fast and
in-process -- the wire protocol itself is exercised by `test_acp.py`.
"""
import json

from exhash import lnhash

from ramabana.racp import Session
from ramabana.testing import MemHost


class _HostOnly:
    "Just enough of a `Session` for `_after_text`: it only reads `self.host`."
    def __init__(self, host): self.host = host


def test_after_text_replays_replace_text_and_edit_file_without_writing_anything():
    host = MemHost({'/proj/a.py': 'def a():\n    return 1\n'})
    sess = _HostOnly(host)

    spec = json.dumps([{'oldText': 'return 1', 'newText': 'return 2'}])
    before, after = Session._after_text(sess, 'replace_text', '/proj/a.py', {'spec': spec})
    assert before == 'def a():\n    return 1\n'
    assert after == 'def a():\n    return 2\n'
    assert host.files['/proj/a.py'] == before, 'a diff preview must never write to the host'

    addr = lnhash(2, '    return 1')
    commands = json.dumps([[addr, 's', 'return 1', 'return 2']])
    before2, after2 = Session._after_text(sess, 'edit_file', '/proj/a.py', {'commands': commands})
    assert before2 == before and after2 == after

    assert Session._after_text(sess, 'replace_text', '/proj/a.py', {'spec': '[bad json'}) is None
