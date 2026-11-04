"Mods in the engine: what `before_turn` returns, `inject`, `ask_user`, `/mods` and `session_end`, through an agent on a scripted model."
import re

from ramabana.agent import Approvals
from ramabana.testing import ScriptedBackend, Step, fake_agent

HELLO = r'''
def setup(reg):
    reg.command('hello', lambda agent, arg: 'hi there')
    reg.status(lambda agent: 'hello up')
'''


def _modded(tmp_path, **kw):
    "An agent that loads `<cfg>/mods/hello.py`."
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods'/'hello.py').write_text(HELLO)
    return fake_agent(cfg=tmp_path, extensions=True, **kw)


def test_a_refused_turn_makes_no_model_call_and_says_why():
    a, be = fake_agent(replies=['never said'])
    a.registry.on('before_turn', lambda agent, prompt: 'quiet hours until 9')
    said = a.ask('write the report')
    assert be.sent == [] and 'quiet hours until 9' in said, (be.sent, said)
    assert 'quiet hours until 9' in ''.join(a.stream('write it anyway')) and be.sent == []
    row = a.history[-1]
    assert row['state'] == 'refused' and row['prompt'] == 'write it anyway' and 'prompt_original' not in row


def test_a_rewrite_and_added_context_reach_the_model_and_the_history_and_a_resume(tmp_path):
    a, be = fake_agent(replies=['ok'], cfg=tmp_path)
    a.registry.on('before_turn', lambda agent, prompt: {'prompt': prompt.upper()})
    a.registry.on('before_turn', lambda agent, prompt: {'context': 'the build is red'})
    a.ask('fix it')
    sent = be.sent[0]
    assert sent.startswith('FIX IT') and 'fix it' not in sent and '<mod-context>\nthe build is red\n</mod-context>' in sent, sent
    row = a.history[-1]
    assert (row['prompt'], row['prompt_original']) == ('FIX IT', 'fix it')
    assert row['context_added'] == [{'mod': None, 'text': 'the build is red', 'where': 'start'}]
    b, _ = fake_agent(cfg=tmp_path)
    b.resume_session(a.session_id, keep_model=True)
    first = b._be('turn').snapshot_hist()[0]['content']
    assert first.startswith('FIX IT') and 'the build is red' in first, first


def test_inject_joins_the_next_turn_once_or_the_running_turn_after_a_tool_call():
    a, be = fake_agent(replies=['ok', 'ok'])
    a.inject('the user is in a meeting')
    a.ask('summarise')
    a.ask('again')
    assert 'the user is in a meeting' in be.sent[0] and 'meeting' not in be.sent[1]
    assert a.history[-2]['context_added'] == [{'mod': None, 'text': 'the user is in a meeting', 'where': 'start'}] and 'context_added' not in a.history[-1]
    a.registry.on('after_tool', lambda agent, name, out: agent.inject(f'saw {name}'))
    sb = ScriptedBackend(steps=[Step(tool=('view_file', {'path': '/proj/a.py'})), Step('read it')], token_delay=0, tools=a.tools, sp=a.system_prompt())
    a._be = a._be_or_none = lambda job='turn': sb
    a.ask('read a.py')
    result = next(m['content'] for m in sb.hist_ if m['role'] == 'tool')
    assert '<mod-context>\nsaw view_file\n</mod-context>' in result, result
    assert a.history[-1]['context_added'] == [{'mod': None, 'text': 'saw view_file', 'where': 'tool'}]


FIRST = r'''
def setup(reg):
    reg.on('before_turn', lambda agent, prompt: {'prompt': prompt + ' carefully'})
    reg.command('remind', lambda agent, arg: agent.inject(arg))
'''

SECOND = r'''
def setup(reg):
    reg.on('before_turn', lambda agent, prompt: {'prompt': prompt + ' with a test', 'context': 'the build is red'})
'''


def test_rewrites_chain_and_each_piece_of_context_names_its_mod(tmp_path):
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods'/'a_first.py').write_text(FIRST)
    (tmp_path/'mods'/'b_second.py').write_text(SECOND)
    a, be = fake_agent(replies=['ok'], cfg=tmp_path, extensions=True)
    a.command('/remind the user is in a meeting')
    a.ask('fix it')
    sent = be.sent[0]
    assert sent.startswith('fix it carefully with a test'), sent
    assert '<mod-context mod="a_first">\nthe user is in a meeting\n</mod-context>' in sent and '<mod-context mod="b_second">\nthe build is red\n</mod-context>' in sent, sent
    row = a.history[-1]
    assert (row['prompt'], row['prompt_original']) == ('fix it carefully with a test', 'fix it')
    assert row['context_added'] == [{'mod': 'a_first', 'text': 'the user is in a meeting', 'where': 'start'},
                                    {'mod': 'b_second', 'text': 'the build is red', 'where': 'start'}]


def test_context_stays_queued_when_the_request_fails_before_it_is_sent():
    a, be = fake_agent(replies=['ok', 'ok'])
    a.ask('warm up')
    a.inject('first')
    a.inject('second')
    a.registry.on('before_turn', lambda agent, prompt: {'context': 'from the hook'})
    be._used = 10**6   # a window already full: `ContextFull` stops the turn before its request is sent
    a.ask('summarise')
    assert len(be.sent) == 1 and a.history[-1]['state'] == 'failed' and 'context_added' not in a.history[-1], a.history[-1]
    be._used = 0
    a.ask('summarise')
    assert be.sent[1].index('first') < be.sent[1].index('second') and be.sent[1].count('from the hook') == 1, be.sent
    assert [e['text'] for e in a.history[-1]['context_added']] == ['first', 'second', 'from the hook']


def test_a_refusal_keeps_unread_steering_for_the_next_turn_and_ends_its_run_refused():
    a, be = fake_agent(replies=['one', 'two'])
    a.ask('first')
    a.run().tell('UNREAD')
    quiet = [True]
    a.registry.on('before_turn', lambda agent, prompt: 'quiet hours' if quiet[0] else None)
    a.ask('second')
    assert (a.run().state, a.run().terminal) == ('refused', True)
    ''.join(a.stream('third'))
    assert a.run().state == 'refused'
    quiet[0] = False
    a.ask('fourth')
    assert len(be.sent) == 2 and 'UNREAD' in be.sent[1], be.sent


def test_ask_user_with_nobody_listening_is_refused_even_by_a_gate_that_waits():
    gate = Approvals(no_listener='wait', timeout=5)
    a, _ = fake_agent(approvals=gate)
    q = a.ask_user('Take a break?', 'You have worked 50 minutes.', timeout=1)
    assert q.answer is False and 'nothing is listening' in q.note, q.note
    assert gate.no_listener == 'wait'


def test_ask_user_goes_to_a_person_and_no_saved_rule_or_mode_answers_it():
    gate = Approvals(mode='auto')
    gate.always('ask user', '*', glob=True)
    a, _ = fake_agent(approvals=gate)
    nobody = a.ask_user('Take a break?', 'You have worked 50 minutes.')
    assert nobody.answer is False and 'nothing is listening' in nobody.note
    stop = gate.listen(on_ask=lambda q: gate.answer(q.id, True))
    yes = a.ask_user('Take a break?', 'You have worked 51 minutes.')
    stop()
    assert yes.answer is True and yes.preview == 'You have worked 51 minutes.'
    gate.listen(on_ask=lambda q: gate.answer(q.id, False, 'later'))
    no = a.ask_user('Take a break?', 'You have worked 52 minutes.')
    assert (no.answer, no.note) == (False, 'later')


def test_mods_off_and_on_through_the_command_dispatch(tmp_path):
    a, _ = _modded(tmp_path)
    listing = a.command('/mods')
    assert any(l.split()[:2] == ['hello', 'on'] for l in listing.splitlines()), listing
    assert a.command('/extensions') == listing and 'mods' in a.commands()
    assert a.command('/hello') == 'hi there' and 'hello up' in a.status()['mod_status']
    assert a.command('/mods off hello').startswith('hello: off')
    assert a.command('/hello') is None and 'hello up' not in a.status()['mod_status']
    assert any(l.split()[:2] == ['hello', 'off'] for l in a.command('/mods').splitlines())
    assert a.command('/mods on hello').startswith('hello: on') and a.command('/hello') == 'hi there'
    assert a.command('/mods off nope').startswith("no mod named 'nope'")


def test_a_status_segment_may_read_the_status_and_mods_lists_one_aligned_line_each():
    a, _ = fake_agent()
    a.registry.add_mod('weather', lambda reg: reg.status(lambda agent: f"sunny · {agent.status()['pct_full']}% full"))
    a.registry.add_mod('release_checklist_gate', lambda reg: None)
    assert [s for s in a.status()['mod_status'] if s.startswith('sunny · ')] == a.mod_status() != [], a.mod_status()
    listing = a.command('/mods')
    assert 'failed' not in listing, listing
    rows = [re.match(r'(\S+ {2,})(on |off) {2}(.*)', line) for line in listing.splitlines()]
    assert all(rows) and len({len(r[1]) for r in rows}) == 1, listing
    assert [(r[1].strip(), r[2].strip(), r[3]) for r in rows] == [('weather', 'on', '1 status'), ('release_checklist_gate', 'on', 'nothing registered')], listing


def test_a_mod_left_out_of_the_allow_list_runs_no_code_until_switched_on(tmp_path):
    ran = tmp_path/'ran.txt'
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods'/'counted.py').write_text(f"open({str(ran)!r}, 'a').write('loaded ')\n"
                                              f"def setup(reg):\n    open({str(ran)!r}, 'a').write('setup ')\n"
                                              "    reg.command('counted', lambda agent, arg: 'counted')\n")
    a, _ = fake_agent(cfg=tmp_path, extensions=True, mods=('other',))
    assert a.command('/counted') is None and not ran.exists()
    assert a.command('/mods on counted').startswith('counted: on') and a.command('/counted') == 'counted'
    assert ran.read_text() == 'loaded setup '


def test_a_mods_allow_list_turns_the_rest_off_and_no_extensions_loads_none(tmp_path):
    a, _ = _modded(tmp_path, mods=('other',))
    assert a.command('/hello') is None and any(l.split()[:2] == ['hello', 'off'] for l in a.command('/mods').splitlines())
    bare, _ = fake_agent(cfg=tmp_path)
    assert bare.command('/hello') is None and bare.command('/mods') == 'no mods loaded'


def test_session_end_fires_once_when_the_session_closes():
    a, _ = fake_agent()
    seen = []
    a.registry.on('session_end', lambda agent: seen.append(agent))
    a.close(); a.close()
    assert seen == [a]
