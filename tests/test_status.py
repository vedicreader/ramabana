"""Status lines: the short line a model writes before each call, kept per run for the `now` pane."""
from ramabana.agent import Agent
from ramabana.runtime import Run, said_before_call, status_line
from ramabana.testing import FakeBackend, MemHost, ScriptedBackend, Step, fake_agent
from ramabana.tools import delegate, sub_briefing

READ = ('view_file', {'path': '/proj/a.py'})
ASKED = '-ing form'


def view(path: str) -> str:
    "Read `path`."
    return 'def a(): pass'


class Narrating(FakeBackend):
    "Says a line, then calls its first tool, recorded the way a tool loop records it."
    def __init__(self, *a, said='Checking the imports.', **kw): super().__init__(*a, **kw); self.said = said
    def spawn(self, sp='', tools=(), **kw):
        self.sub = type(self)(self.spec, sp=sp, tools=tools, said=self.said, shared=True)
        return self.sub
    def _send(self, msg, **kw):
        t = next((t for t in self.tools if t.__name__ in ('view', 'view_file')), None)
        self.hist_.append({'role': 'assistant', 'content': f'Some thinking first.\n{self.said}',
                           'tool_calls': [{'id': '1', 'function': {'name': t.__name__, 'arguments': {'path': '/proj/a.py'}}}]})
        self.seen = t(path='/proj/a.py')
        return 'a.py defines a()'


def test_every_briefing_asks_for_a_status_line_before_each_call():
    a, _ = fake_agent()
    assert ASKED in a.system_prompt()
    small = Agent(MemHost({'/proj/a.py': ''}), extensions=False, profile='small')
    assert ASKED in small.system_prompt() and len(small.system_prompt()) <= 4000
    assert ASKED in sub_briefing() and ASKED in sub_briefing(writes=True)


def test_a_status_is_the_last_line_worth_showing():
    assert status_line('Looked at it.\n\nReading the config loader.\n') == 'Reading the config loader.'
    assert status_line('Reading the loader.\n> **🧠 Thinking**\n>\n> hmm') == 'Reading the loader.', 'a thinking quote is not a status'
    assert status_line('') == '' and status_line('\n  \n') == ''
    long = status_line('Reading ' + 'very ' * 40 + 'long')
    assert len(long) <= 80 and '\n' not in long and long.startswith('Reading very')


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


def test_a_turn_with_no_narration_keeps_the_last_status_and_a_new_turn_starts_blank():
    a, _ = fake_agent()
    be = ScriptedBackend(steps=[Step('Reading it.'), Step(tool=READ), Step(tool=READ), Step('done')], token_delay=0, tools=a.tools)
    a._be = a._be_or_none = lambda job='turn': be
    list(a.stream('go'))
    assert a.status_line == 'Reading it.'
    be.steps = [Step('ok')]
    list(a.stream('again'))
    assert a.status_line == ''


def test_a_sub_agent_status_comes_from_the_message_that_made_its_call(tmp_path):
    be = Narrating()
    run = Run('run_sub', 'child', 'what does a.py define?', log=tmp_path/'run_sub.log')
    assert delegate(be, 'what does a.py define?', tools=[view], run=run) == 'a.py defines a()'
    assert run.status == 'Checking the imports.' and be.sub.seen == 'def a(): pass'
    assert '~ Checking the imports.' in run.log.read_text()
    assert 'status' not in {t.__name__ for t in be.sub.tools}, 'a backend whose text is seen needs no status tool'


def test_a_sub_agent_on_a_backend_that_hides_its_text_gets_a_status_tool():
    class Quiet(FakeBackend):
        narrates = False
        def spawn(self, sp='', tools=(), **kw):
            self.sub = FakeBackend(self.spec, sp=sp, tools=tools, shared=True)
            self.sub._send = lambda msg, **kw: next(t for t in self.sub.tools if t.__name__ == 'status')(text='Reading the tests')
            return self.sub
    be, run = Quiet(), Run('run_q', 'child', 'q')
    assert delegate(be, 'q', tools=[view], run=run)
    assert run.status == 'Reading the tests'
    assert '`status`' in be.sub.sp


def test_the_snapshot_carries_the_root_and_sub_agent_status():
    from ramabana.pane import now_snapshot
    a, _ = fake_agent()
    seen = []
    def peek(act):
        if act.run_id and act.done: seen.append(now_snapshot(a))
    a.activity.on_change = peek
    class Root(ScriptedBackend):
        def spawn(self, sp='', tools=(), **kw): return Narrating(self.spec).spawn(sp, tools)
    be = Root(steps=[Step('Asking a sub-agent.'), Step(tool=('delegate_search', {'questions': ['what does a.py define?']})), Step('done')],
              token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': be
    list(a.stream('go'))
    snap = seen[0]
    assert snap['root']['status'] == 'Asking a sub-agent.'
    assert snap['subs'][0]['status'] == 'Checking the imports.'


def test_every_briefing_says_the_ing_form_and_the_root_asks_once():
    from ramabana.agent import RULES, SMALL_RULES
    for rules in (RULES, SMALL_RULES): assert sum('-ing form' in t for _, t in rules) == 1
    assert '-ing form' in sub_briefing()
    assert not any('Start every user-facing response' in t for _, t in RULES), 'one instruction about narrating, not two'


def test_a_status_skips_fences_and_drops_bullets_and_bold():
    assert status_line('- **Reading** the loader.\n```') == 'Reading the loader.'
    assert status_line('Checking it.\n```python\n') == 'Checking it.'
    assert status_line('1. Running the tests.') == 'Running the tests.'


def test_a_finished_run_keeps_no_streamed_text():
    r = Run('run_h')
    r.start()
    r.hear('the whole final answer ' * 50)
    r.finish()
    assert r._heard == []


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


class _Quiet(FakeBackend):
    narrates = False
    def spawn(self, sp='', tools=(), **kw):
        self.sub = FakeBackend(self.spec, sp=sp, tools=tools, shared=True)
        self.sub.max_steps = 0
        self.sub._send = lambda msg, **kw: next(t for t in self.sub.tools if t.__name__ == 'status')(text='Reading the tests')
        return self.sub


def test_status_calls_leave_a_quiet_sub_agent_its_real_step_budget():
    be = _Quiet()
    delegate(be, 'q', tools=[view], run=Run('run_b', 'child', 'q'), max_steps=12)
    assert be.sub.max_steps == 24, 'one status call per real call'


def test_a_root_on_a_backend_that_hides_its_text_gets_the_status_tool():
    from ramabana.core import ModelSpec
    a, be = fake_agent()
    a.routing._cache['fake'] = ModelSpec('fake', 'litert', 'fake/model', ctx=1000)
    assert 'status' in {t.__name__ for t in a.tools} and '`status`' in a.system_prompt()
    status = next(t for t in a.tools if t.__name__ == 'status')
    assert status(text='idle') and a.status_line == '', 'with no turn running it is a no-op'
    be.replies = ['ok']
    be._send = lambda msg, **kw: (status(text='Reading the tests'), 'ok')[1]
    a.ask('go')
    assert a.status_line == 'Reading the tests' and not a.activity.acts, 'display-only: no act'
    b, _ = fake_agent()
    assert 'status' not in {t.__name__ for t in b.tools}


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
