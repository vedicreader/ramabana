"""The terminal's diff surface: the one thing a person is actually being asked to read."""
from ramabana.agent import edit_preview, preview_for
from ramabana.cli import changes_patch, diff_stat, diff_text, is_diff
from ramabana.tools import unified


def test_a_patch_is_coloured_without_being_altered():
    patch = unified('value = 1\n', 'value = 2\n', 'app.py')
    assert is_diff(patch) and diff_stat(patch) == '+1 −1'
    assert diff_text(patch).plain == patch, 'colour only, never a character more or less'
    spans = {diff_text(patch).plain[s.start:s.end]: str(s.style) for s in diff_text(patch).spans}
    assert spans['+value = 2'] != spans['-value = 1']
    assert spans['-value = 1'] != spans['--- a/app.py']

def test_only_diff_shaped_text_is_treated_as_a_diff():
    assert not is_diff('replaced 1 block(s) in app.py')
    assert not is_diff('')
    assert is_diff('diff --git a/x b/x\n+one')
    assert diff_text('plain output').plain == 'plain output'

def test_a_turn_is_one_patch_across_every_file_it_moved():
    patch = changes_patch({'b.py': ('1\n', '1\n2\n'), 'a.py': ('x\n', 'y\n')})
    assert patch.index('a/a.py') < patch.index('a/b.py'), 'sorted, so a turn reads the same twice'
    assert diff_stat(patch) == '+2 −1'
    assert changes_patch({}) == ''

def test_an_edit_is_previewed_as_the_patch_it_will_apply():
    "The approval used to show a JSON blob of the edits, which is not what a person is judging."
    preview = preview_for('replace_text', {'path': 'app.py',
        'edits': '[{"oldText": "value = 1", "newText": "value = 2"}]'})
    assert is_diff(preview) and '-value = 1' in preview and '+value = 2' in preview
    assert preview_for('replace_text', {'path': 'a.py', 'edits': 'not json'}) == 'not json'
    assert edit_preview('a.py', [['one', 'two']]).endswith('-one\n+two')
