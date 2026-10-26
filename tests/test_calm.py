"""Calm mode: the conversation shows the user's text, the narration and the replies, and each stretch of
activity between two of them folds into one `work` block with a summary row.

Nothing here loads a model, and nothing here touches a real terminal.
"""
import time
from types import SimpleNamespace

from ramabana.agent import Act
from test_timeline import a_turn, ui  # noqa: F401  (`ui` is a fixture)

THREE = [('Looking for it.\n', 'search_code', 'runtime.py:88'),
         ('And the caller.\n', 'view_file', 'line 120'),
         ('And the tests.\n', 'search_code', 'test_context.py:44')]


def kinds(u): return [u.kind(b) for b in u.comp.blocks.values()]


def test_with_calm_off_every_call_keeps_its_own_block(ui):
    a_turn(ui, THREE)
    assert kinds(ui) == ['step', 'tool', 'step', 'tool', 'step', 'tool', 'reply']


def test_calm_folds_each_stretch_into_one_work_block(ui):
    ui.calm = True
    blocks = a_turn(ui, THREE)
    assert [ui.kind(b) for b in blocks] == ['step', 'work', 'step', 'work', 'step', 'work', 'reply']
    for b in (b for b in blocks if ui.kind(b) == 'work'):
        assert b.collapsed and len(ui.comp._block_rows(b)) == 1, 'one summary row until it is opened'
        assert '1 tool call' in ui.transcript.block_text(b)
        ui.toggle(b.key)
        assert not b.collapsed and len(ui.comp._block_rows(b)) > 1


def test_a_stretch_gathers_every_call_between_two_text_blocks(ui):
    ui.calm = True
    acts = ui.agent.activity
    ui.stream(None, 'Looking.\n')
    for q in 'abc': acts.finish(acts.start('search_code', {'query': q}), 'hit')
    ui.stream(None, 'Done.\n')
    ui.flush_stream()
    work = [b for b in ui.comp.blocks.values() if ui.kind(b) == 'work']
    assert len(work) == 1 and ui.transcript.block_text(work[0]).startswith('3 tool calls')


def test_errors_and_questions_are_never_inside_a_work_block(ui):
    ui.calm = True
    acts = ui.agent.activity
    acts.finish(acts.start('search_code', {'query': 'a'}), 'hit')
    ui.note('boom', 'error')
    ui.ask = SimpleNamespace(summary='write x.py')
    ui.reask('overwrites it')
    acts.finish(acts.start('view_file', {'path': 'a.py'}), 'line')
    got = [(ui.kind(b), ui.transcript.block_text(b)) for b in ui.comp.blocks.values()]
    assert [k for k, _ in got][-4:] == ['work', 'error', 'ask', 'work']
    assert all('boom' not in t and 'write x.py' not in t for k, t in got if k == 'work')


def test_while_calm_the_working_footer_is_one_row(ui):
    ui.calm = True
    ui.turn, ui._turn_at = 'a turn', time.monotonic()
    acts = ui.agent.activity
    acts.start('search_code', {'query': 'a'}); acts.start('view_file', {'path': 'a.py'})
    rows = ui.working()
    assert len(rows) == 1 and rows[0].plain.strip().startswith('working · 2 tool calls · ')


def test_the_calm_command_sets_the_flag(ui):
    for line, want in (('/calm on', True), ('/calm off', False), ('/calm', True), ('/calm', False)):
        ui.buf.insert(line)
        assert ui.submit() is None and ui.calm is want, line
    ui.buf.insert('/calm sideways'); ui.submit()
    assert ui.calm is False and 'usage: /calm' in ui.transcript.block_text(list(ui.comp.blocks.values())[-1])


def test_the_summary_names_calls_files_sub_agents_and_failures():
    from ramabana.cli import stretch_summary
    def call(tool, path='', ok=True, parent='', id=None):
        return Act(tool=tool, args={'path': path} if path else {}, ok=ok, done=True, parent_action_id=parent, **({'id': id} if id else {}))
    assert stretch_summary([]) == ''
    assert stretch_summary([call('search_code')]) == '1 tool call'
    assert stretch_summary([call('create_file', 'a.py')]) == '1 tool call · 1 file changed'
    acts = [call('search_code'), call('view_file', 'a.py'), call('create_file', 'a.py'), call('edit_file', 'a.py'),
            call('create_file', 'b.py'), call('edit_file', 'c.py', ok=False), call('delegate_search', id='d'),
            call('search_code', parent='d')]
    assert stretch_summary(acts) == '7 tool calls · 2 files changed · 1 sub-agent · 1 failed'
    assert stretch_summary([Act(tool='run_shell')]) == '1 tool call'
