"""Status lines: the short line a model writes before each call, kept per run for the `now` pane."""
from ramabana.runtime import Run, said_before_call
from ramabana.testing import ScriptedBackend, Step, fake_agent

READ = ('view_file', {'path': '/proj/a.py'})
def test_the_root_status_is_the_narration_streamed_before_its_call():
    a, _ = fake_agent()
    seen = []
    def peek(act):
        if not act.done: seen.append(a.status_line)
    a.activity.on_change = peek
    be = ScriptedBackend(steps=[Step('Reading the module now.'), Step(tool=READ), Step('Checking again.'), Step(tool=READ), Step('done')],
                         token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    list(a.stream('go'))
    assert seen == ['Reading the module now.', 'Checking again.']
    assert a.status_line == 'Checking again.', 'the final answer is not a status: no call followed it'


def test_the_tool_loop_every_narrating_rishi_backend_uses_records_the_calling_message_before_the_tool_runs():
    from rishi.core import RishiToolLoop
    from rishi.claude import ClaudeChat
    from rishi.remote import RemoteChat
    from urai import Chat, ToolLoopMixin
    for c in (ClaudeChat, RemoteChat): assert c._send is ToolLoopMixin._send and c._run_tools is ToolLoopMixin._run_tools
    seen = []
    class Loop(RishiToolLoop, Chat):
        def _model_step(self, **kw):
            if any(m.get('role') == 'tool' for m in self.hist): return {'role': 'assistant', 'content': 'done'}
            return {'role': 'assistant', 'content': 'Reading the loader.',
                    'tool_calls': [{'id': '1', 'type': 'function', 'function': {'name': 'look', 'arguments': {'path': 'a'}}}]}
    def look(path: str) -> str:
        "Read `path`."
        seen.append(said_before_call(chat.hist))
        return 'x'
    chat = Loop('x', tools=[look]); chat._set_tools([look])
    chat('go')
    assert seen == ['Reading the loader.']


def test_each_narration_is_kept_whole_as_a_note_for_the_pane():
    "The status line keeps a clipped last line; the pane's notes keep what the model said, minus its thinking quotes."
    from ramabana.pane import now_snapshot
    a, _ = fake_agent()
    long = 'Reading the module now, because the loader decides the default.\nThen the tests.'
    be = ScriptedBackend(steps=[Step(long), Step(tool=READ), Step('> **🧠 Thinking**\n>\n> hmm\nChecking again.'), Step(tool=READ), Step('done')],
                         token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    list(a.stream('go'))
    notes = [t for _, t in a.run().notes]
    assert [n.strip() for n in notes] == [long, 'Checking again.'], notes
    assert [n['text'].strip() for n in now_snapshot(a)['notes']] == [long, 'Checking again.']


def test_one_message_making_several_calls_is_one_note():
    "Batched calls each start through `on_call`; the later ones fall back to the same message, which is not a new note."
    from types import SimpleNamespace
    r = Run('run_batch')
    r.backend = SimpleNamespace(hist=[{'role': 'assistant', 'content': 'Reading both files.', 'tool_calls': [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]}])
    r.hear('Reading both files.')
    for _ in range(3): r.on_call()
    r.hear('Now the tests.'); r.on_call()
    assert [t for _, t in r.notes] == ['Reading both files.', 'Now the tests.'], r.notes
