"""`/rewind files` and `/redo`: a file this turn created is removed on rewind rather than left
empty, when the host can delete; `/redo` is the complement, putting files back to after the turn.
"""
from ramabana.testing import MemHost, fake_agent


def _wrote_a_new_file(a, host, path='/proj/new.py', text='X = 1\n'):
    a._prepare('add a file')
    look = next(t for t in a.tools if t.__name__ == 'create_file')
    look(path=path, text=text)


def test_rewind_removes_a_file_the_turn_created_when_the_host_can_delete(tmp_path):
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    _wrote_a_new_file(a, host)
    a._finish('done')

    snap = a._load_checkpoint(a.current_turn_id)
    assert snap['new'] == ['/proj/new.py'] and snap['before']['/proj/new.py'] == ''
    assert snap['after']['/proj/new.py'] == 'X = 1\n'

    out = a.command('/rewind files')
    assert 'removed' in out and '/proj/new.py' not in host.files

    redone = a.command('/redo')
    assert 'restored' in redone and host.files['/proj/new.py'] == 'X = 1\n'


def test_rewind_empties_a_created_file_when_the_host_cannot_delete(tmp_path):
    class NoDelete(MemHost):
        delete = None   # not callable: hasattr still True, so exercise the except-and-fall-back path

    host = NoDelete({'/proj/a.py': 'def a(): pass\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    _wrote_a_new_file(a, host)
    a._finish('done')

    out = a.command('/rewind files')
    assert 'could not be removed, left empty' in out
    assert host.files['/proj/new.py'] == ''


def test_redo_reports_when_there_is_no_checkpoint(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    assert 'no file checkpoint' in a.redo('nosuchturn')
