"""Instruction files, edit previews, saved approval rules, the verify gate, file rewind and file memory."""
import json

from ramabana.testing import MemHost, fake_agent


def test_rewind_removes_the_files_a_turn_created_and_restores_the_ones_it_changed(tmp_path):
    "A file that did not exist before the turn is deleted, not left as an empty file; a second write to it is the same change."
    host = MemHost({'/proj/a.py': 'def a(): pass\n'})
    a, _ = fake_agent(host, cfg=tmp_path)
    tools = {t.__name__: t for t in a.tools}
    a._prepare('add b')
    tools['create_file']('/proj/b.py', 'x = 1\n')
    tools['create_file']('/proj/a.py', 'def a(): return 1\n')
    tools['create_file']('/proj/b.py', 'x = 2\n')
    assert a.new == {'/proj/b.py'}
    a._finish('done')
    a.command('/rewind files')
    assert host.files == {'/proj/a.py': 'def a(): pass\n'}


def _full_agent(tmp_path, files):
    from ramabana.testing import FullHost
    host = FullHost(files=files)
    a, _ = fake_agent(host, cfg=tmp_path)
    return a, host, {t.__name__: t for t in a.tools}


def test_a_refused_write_leaves_nothing_for_rewind_to_undo(tmp_path):
    "A `create_file` the sandbox refuses never ran, so it is neither a change nor a created file; the turn's real edit still rewinds cleanly."
    a, host, tools = _full_agent(tmp_path, {'a.py': 'x = 1\n'})
    a._prepare('write')
    tools['create_file']('/etc/nope.txt', 'boo')
    tools['create_file']('a.py', 'x = 2\n')
    assert a.new == set() and list(a.before) == ['a.py'], (a.new, a.before)
    a._finish('done')
    a.command('/rewind files')
    assert (host.root/'a.py').read_text() == 'x = 1\n'


def test_a_created_file_the_person_changed_since_is_kept_and_said_so(tmp_path):
    a, host, tools = _full_agent(tmp_path, {})
    a._prepare('make b')
    tools['create_file']('b.py', 'x = 1\n'); tools['create_file']('c.py', 'y = 1\n')
    a._finish('done')
    (host.root/'b.py').write_text('x = 1\nmine = True\n')
    a.command('/rewind files')
    assert (host.root/'b.py').read_text() == 'x = 1\nmine = True\n' and not (host.root/'c.py').exists()


def test_a_binary_pre_image_is_reported_as_unrestorable_rather_than_emptied(tmp_path):
    from shalya.core import writes
    a, host, tools = _full_agent(tmp_path, {'a.py': 'x = 1\n'})
    (host.root/'img.bin').write_bytes(b'\x89PNG\xff\xfe\x00')
    # `create_file` refuses a binary target, so a writer that does not is what reaches this path
    @writes
    def stamp(path: str, text: str) -> str: (host.root/path).write_text(text); return 'ok'
    a._prepare('overwrite')
    a._record(stamp)('img.bin', 'text now\n'); tools['create_file']('a.py', 'x = 2\n')
    assert a.binary == {'img.bin'}
    a._finish('done')
    a.command('/rewind files')
    assert (host.root/'img.bin').read_text() == 'text now\n' and (host.root/'a.py').read_text() == 'x = 1\n'


def test_rewind_puts_a_notebook_back_byte_for_byte(tmp_path):
    "`text_at` shows a notebook as its cell text, so a pre-image taken from it would replace the JSON with plain text."
    from fastcore.nbio import mk_cell, new_nb, read_nb, write_nb
    a, host, tools = _full_agent(tmp_path, {})
    nb = host.root/'n.ipynb'
    write_nb(new_nb([mk_cell('x = 1', id='c1'), mk_cell('y = 2', id='c2')]), nb)
    original = nb.read_bytes()
    a._prepare('edit the notebook')
    tools['edit_cell']('n.ipynb', 'c1', [{'oldText': 'x = 1', 'newText': 'x = 5'}])
    tools['add_cell']('n.ipynb', 'z = 3')
    assert a.changes()['n.ipynb'] == ('x = 1\n\ny = 2', 'x = 5\n\ny = 2\n\nz = 3'), 'the pane diffs cell text'
    a._finish('done')
    a.command('/rewind files')
    assert nb.read_bytes() == original
    assert [c.source for c in read_nb(nb).cells] == ['x = 1', 'y = 2']
