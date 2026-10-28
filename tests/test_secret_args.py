"A tool argument named in `secret_args` reaches the tool and is never kept: not in calls, rows, asks, events or the saved conversation."
import json
from ramabana import agent
from ramabana.agent import Approvals
from ramabana.testing import fake_agent

S = 'SENTINEL-the-reference-answer'
got = []

def add_exercise(task: str, solution: str = ''):
    "Add an exercise."
    got.append(solution)
    return 'added'
add_exercise.secret_args = ('solution',)

def note(text: str):
    "Note a text."
    return 'noted'

def _ex(rows): return json.dumps([r for r in rows if 'add_exercise' in json.dumps(r)])

def test_a_secret_argument_reaches_the_tool_and_nothing_keeps_it(tmp_path):
    a, be = fake_agent(cfg=tmp_path, keep_conversation=True)
    ev = a.events_to(tmp_path/'events.jsonl')
    got.clear()
    assert a._record(add_exercise)(task='double it', solution=S) == 'added' and got == [S], 'the tool gets the real value'
    a._record(note)(text=S)
    assert a.calls == [('add_exercise', {'task': 'double it', 'solution': '[SECRET]'}), ('note', {'text': S})], 'an unmarked tool keeps its arguments'
    rows = [x.dict() for x in a.activity.acts]
    assert S not in _ex(rows) and S in json.dumps(rows)
    be.hist_ += [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function',
                  'function': {'name': 'add_exercise', 'arguments': json.dumps({'task': 'double it', 'solution': S})}}]},
                 {'role': 'tool', 'tool_call_id': 'c1', 'content': 'added'}]
    a.ask('go on')
    saved = (a.runs_dir/agent.HIST).read_text()
    assert S not in saved and '[SECRET]' in saved and 'double it' in saved
    assert S in json.dumps(be.hist_), 'the live conversation keeps what the model wrote'
    assert S not in _ex(a.history[-1]['activity'])
    assert S not in _ex(json.loads(l) for l in ev.read_text().splitlines())

def test_an_approval_ask_shows_the_placeholder_and_the_call_runs_with_the_real_value(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    t = a._record(add_exercise)
    ask = Approvals(mode='ask').ask('add_exercise', {'task': 'double it', 'solution': S})
    assert S not in json.dumps([ask.args, ask.summary, ask.preview, ask.dict()]), ask
    got.clear()
    assert t(task='double it', solution=S) == 'added' and got == [S]

def test_an_ask_a_host_builds_with_the_real_value_keeps_nothing(tmp_path):
    "A host that builds its own `Ask` gives it the real arguments, and a summary and preview made from them."
    from ramabana.agent import Ask
    a, _ = fake_agent(cfg=tmp_path)
    ev = a.events_to(tmp_path/'events.jsonl')
    a._record(add_exercise)
    real = {'task': 'double it', 'solution': S}
    mk = lambda: Ask(tool='add_exercise', args=dict(real), summary=f'add_exercise(solution={S!r})', preview=json.dumps(real))
    for ok in (True, False):
        ask = mk(); a._ask_raised(ask); ask.resolve(ok); a._ask_settled(ask)
    unasked = mk(); unasked.resolve(False, 'refused by the policy'); a._ask_settled(unasked)   # a row with no raise
    rows = [x.dict() for x in a.activity.acts]
    assert len(rows) == 3 and S not in json.dumps(rows) and all(r['args']['solution'] == '[SECRET]' for r in rows), rows
    assert S not in ev.read_text() and '"tool": "add_exercise"' in ev.read_text()
    a.activity._mark = 0   # the rows came before the turn; count them in it
    a.ask('go on')
    assert S not in json.dumps(a.history[-1]) and S not in a.history_path.read_text()
    assert unasked.args['solution'] == S, 'the Ask itself keeps the real value for the host'
