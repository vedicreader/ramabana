"Per-delegation model and effort, the tool channel for the turn and for sub-agents, and the settings dict every surface shares."
import json, threading, time
import pytest

import ramabana.core as core
from ramabana.agent import Agent
from ramabana.core import ModelSpec, SETUP_HINT, forget_forced_tags, force_tags
from ramabana.runtime import RishiBackend, use_chat
from ramabana.testing import FakeBackend, FullHost, MemHost, SPEC, fake_agent
from ramabana.tools import delegate_many, lanes, subagent_tools

GPT = ModelSpec('gpt', 'remote', 'openai/gpt-5.4', 272_000)
GEM = ModelSpec('gem', 'remote', 'gemini/gemini-3-pro', 1_000_000)
CL = ModelSpec('cl', 'claude', 'claude-sonnet-5', 200_000)
GEMMA = ModelSpec('gemma-e4b', 'litert', 'gemma-e4b', 16_384)
TINY = ModelSpec('tiny', 'remote', 'openai/tiny', 16_000)

class Slow(FakeBackend):
    "A backend whose sub-agents take `wait` seconds and log when each ran."
    log = []
    def __init__(self, spec=SPEC, wait=.2, **kw): super().__init__(spec, **kw); self.wait = wait
    def spawn(self, sp='', tools=(), **kw):
        s = Slow(self.spec, self.wait, sp=sp, tools=tools, shared=True, **kw)
        self.spawned.append(s); return s
    def _send(self, msg, **kw):
        t = time.monotonic(); time.sleep(self.wait); Slow.log.append((self.spec.name, t, time.monotonic()))
        return f'{self.spec.name} answered\nstate: completed'

def _tools(backends, **kw):
    "The delegation tools over a `get_sub` that picks `backends[model]`, '' for the first."
    picked = []
    def get_sub(model, effort):
        picked.append((model, effort, threading.current_thread().name))
        if model and model not in backends: raise core.AgentError(f'{core.unknown_model(model)} {SETUP_HINT}')
        b = backends[model or next(iter(backends))]
        return b, ({'effort': effort} if effort else {}), ''
    dt = {t.__name__: t for t in subagent_tools(lambda: None, lambda: [], get_sub=get_sub, **kw)}
    return dt, picked

def test_model_names_one_model_for_all_or_one_per_question():
    a, b = FakeBackend(GPT), FakeBackend(GEM)
    dt, picked = _tools({'gpt': a, 'gem': b})
    out = dt['delegate_search'](['q1', 'q2'], model=['gpt', 'gem'])
    assert out.count('### ') == 2 and len(a.spawned) == 1 and len(b.spawned) == 1
    dt['delegate_search'](['q1', 'q2'], model='gem')
    assert len(b.spawned) == 3, 'one string is every question'
    dt['delegate_search'](['q1', 'q2'], model='["gpt", "gem"]')
    assert len(a.spawned) == 2, 'a JSON list is a list'
    assert dt['delegate_search'](['q1'], cloud_model='gpt') and len(a.spawned) == 3, '`cloud_model` is still taken'

def test_a_mismatched_list_is_refused_before_any_sub_agent_runs():
    a = FakeBackend(GPT)
    dt, picked = _tools({'gpt': a})
    out = dt['delegate_search'](['q1', 'q2', 'q3'], model=['gpt', 'gpt'])
    assert '2 model values for 3 questions' in out and not a.spawned and not picked
    assert '2 effort values' in dt['delegate_search'](['q1', 'q2', 'q3'], effort=['low', 'high']) and not a.spawned
    assert 'effort is one of' in dt['delegate_search'](['q1'], effort='huge') and not a.spawned

def test_an_unknown_model_fails_alone_with_the_setup_message_and_nothing_falls_back():
    a = FakeBackend(GPT)
    dt, _ = _tools({'gpt': a})
    out = dt['delegate_search'](['q1', 'q2'], model=['gpt', 'nope-9'])
    assert "unknown model 'nope-9'" in out and SETUP_HINT in out and out.count('sub answer') == 1
    assert len(a.spawned) == 1, 'the question on the unknown model never reached another'

def test_questions_on_different_cloud_models_run_at_once():
    Slow.log.clear()
    dt, picked = _tools({'gpt': Slow(GPT), 'gem': Slow(GEM)})
    t = time.monotonic()
    out = dt['delegate_search'](['q1', 'q2'], model=['gpt', 'gem'])
    assert 'gpt answered' in out and 'gem answered' in out
    (_, s1, e1), (_, s2, e2) = Slow.log
    assert s1 < e2 and s2 < e1, 'the two sub-agents overlapped'
    assert {p[2] for p in picked} == {threading.current_thread().name}, 'models resolved in the caller thread'

def test_local_questions_run_one_after_another_and_writes_stay_serial():
    loc, cl1, cl2 = Slow(GEMMA), Slow(GPT), Slow(GEM)
    assert lanes([loc, cl1, loc, cl2]) == [[0, 2], [1], [3]]
    assert lanes([loc, cl1, cl2], writes=True) == [[0, 1, 2]]
    Slow.log.clear()
    delegate_many([loc, loc], ['q1', 'q2'])
    (_, s1, e1), (_, s2, e2) = Slow.log
    assert e1 <= s2 or e2 <= s1, 'one local engine answers one question at a time'

def test_the_effort_reaches_the_sub_agent_and_a_local_model_says_it_ran_without(tmp_path, monkeypatch):
    a, be = fake_agent(cfg=tmp_path)
    monkeypatch.setattr(core, 'setting', lambda k, d=None: {'subagents.effort': 'low'}.get(k, d))
    monkeypatch.setattr('ramabana.agent.setting', lambda k, d=None: {'subagents.effort': 'low'}.get(k, d))
    assert a._sub_backend('', '')[1] == {}, 'the fake runtime takes no effort'
    a._be_or_none = lambda job='turn': FakeBackend(GPT)
    assert a._sub_backend()[1] == {'effort': 'low'}, 'config.toml'
    monkeypatch.setenv('RAMABANA_SUBAGENT_EFFORT', 'medium')
    assert a._sub_backend()[1] == {'effort': 'medium'}, 'the env var beats config.toml'
    a.subagent_settings(effort='high')
    assert a._sub_backend()[1] == {'effort': 'high'}, 'the session beats both'
    assert a._sub_backend('', 'max')[1] == {'effort': 'max'}, 'the delegation beats the session'
    a._be_or_none = lambda job='turn': FakeBackend(GEMMA)
    b, kw, note = a._sub_backend('', 'xhigh')
    assert kw == {} and 'xhigh' in note and 'gemma-e4b' in note
    dt = {t.__name__: t for t in a._delegation_tools(lambda: [])}
    assert '[effort xhigh is not supported on gemma-e4b' in dt['delegate_search'](['q'], effort='xhigh')

def test_a_delegation_is_given_tools_sized_for_the_model_it_runs_on(tmp_path):
    a, _ = fake_agent(FullHost(), cfg=tmp_path)
    bes, dflt = {'tiny': FakeBackend(TINY), 'gpt': FakeBackend(GPT)}, ['tiny']
    a.spec_or_none = lambda job='turn': bes[dflt[0]].spec if job == 'subagent' else GPT
    a._sub_backend = lambda model='', effort='': (bes[model or dflt[0]], {}, '')
    search = {t.__name__: t for t in a.tools}['delegate_search']
    def given(model=''):
        search(['q'], model=model)
        return {t.__name__ for t in bes[model or dflt[0]].spawned[-1].tools}
    small = given()
    assert given('gpt') > small, 'a large model named while the default is small is not held to the small list'
    dflt[0] = 'gpt'
    assert given('tiny') == small < given(), 'a small model named while the default is large is not given the full list'

def test_a_named_model_not_set_up_gives_its_setup_message(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    a.routing._cache['gpt'] = GPT
    with pytest.raises(core.AgentError) as e: a._named_backend('gpt')
    assert 'gpt needs OPENAI_API_KEY' in str(e.value) and SETUP_HINT in str(e.value)
    with pytest.raises(core.AgentError) as e: a._named_backend('no-such-model-zz')
    assert "unknown model 'no-such-model-zz'" in str(e.value) and SETUP_HINT in str(e.value)
    a.routing._cache['gemma-e4b'] = GEMMA
    monkeypatch.setattr('ramabana.agent.missing_runtime', lambda s: '')
    with pytest.raises(core.AgentError) as e: a._named_backend('gemma-e4b')
    assert 'has not loaded' in str(e.value), 'a local model that is not the session engine is refused'

KEYS = {'ok', 'model', 'effort', 'tools', 'note', 'unavailable', 'error'}

def test_subagent_settings_is_one_dict_from_every_route(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_CONFIG', str(tmp_path/'config.toml'))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    a, _ = fake_agent(cfg=tmp_path)
    a.routing._cache['gpt'] = GPT
    shown = a.subagent_settings()
    assert set(shown) == KEYS and shown['ok'] and shown['tools'] == 'auto' and shown['effort'] == ''
    bad = a.subagent_settings(model='gpt')
    assert set(bad) == KEYS and not bad['ok'] and 'needs OPENAI_API_KEY' in bad['error'] and SETUP_HINT in bad['error']
    assert bad['model'] == shown['model'], 'a model not set up is not applied'
    assert a.subagents_command('model gpt') == bad, 'the /subagents path gives the same dict'
    assert a.command('/subagents model gpt') == bad['error'], 'and its text is that error'
    json.dumps(bad)
    monkeypatch.setenv('OPENAI_API_KEY', 'x')
    ok = a.subagent_settings(model='gpt', effort='xhigh', tools='text')
    assert ok['ok'] and (ok['model'], ok['effort'], ok['tools']) == ('gpt', 'xhigh', 'text') and ok['unavailable'] == ''
    assert 'model gpt · effort xhigh · tools text' in a.command('/subagents')
    d = a.subagents_command('effort default --save')
    assert d['ok'] and d['effort'] == '' and 'effort = ""' in (tmp_path/'config.toml').read_text()
    a.subagents_command('tools native --save'); a.subagents_command('model default --save')
    text = (tmp_path/'config.toml').read_text()
    assert '[subagents]' in text and 'tool_channel = "native"' in text and '[jobs]' in text and 'subagent = ""' in text
    assert a.subagent_settings()['model'] == core.DFLT_SUBAGENT, 'default is the routing default again'
    assert not a.subagents_command('effort huge')['ok'] and not a.subagents_command('bogus')['ok']
    monkeypatch.delenv('OPENAI_API_KEY')
    a.routing.set('gpt', 'subagent')
    assert 'needs OPENAI_API_KEY' in a.subagent_settings()['unavailable'], 'a chosen model that cannot run says why'

def test_a_session_or_config_channel_reaches_a_sub_agent(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    a._be_or_none = lambda job='turn': FakeBackend(GPT)
    assert a._sub_backend()[1] == {}, 'the default channel adds nothing to spawn'
    a.subagent_settings(tools='text')
    assert a._sub_backend()[1] == {'tool_mode': 'tags'}
    force_tags(GPT.model_id, 'refused')
    try: assert a._sub_backend()[1] == {}, 'a refusal beats the session'
    finally: forget_forced_tags()

# the parent turn on the native channel, through a chat that calls ramabana's tools as a native backend would

class Native:
    "A rishi chat stand-in: its ctor options are kept and each call runs `script`, calling the tools it was given."
    made, script, hook = [], [], None
    def __init__(self, model_id, **kw):
        self.kw, self.hist, self.calls = kw, [], []
        self.tools = {getattr(t, '__name__', ''): t for t in kw.get('tools') or []}
        Native.made.append(self)
    def __call__(self, msg, stream=False, **kw):
        self.calls.append(kw); self.hist.append({'role': 'user', 'content': str(msg)})
        for name, args in list(Native.script):
            if Native.hook: Native.hook(name)
            ok = (ap := self.kw.get('approve')) is None or name not in WRITES or ap({'name': name, 'arguments': args})
            out = str(self.tools[name](**args)) if ok and name in self.tools else 'refused' if not ok else f'no tool {name}'
            if (mx := self.kw.get('tool_max_len')): out = out[-mx:]
            self.hist += [{'role': 'assistant', 'content': '', 'tool_calls': [{'name': name}]}, {'role': 'tool', 'content': out}]
        self.hist.append({'role': 'assistant', 'content': 'done'})
        return {'role': 'assistant', 'content': 'done'} if not stream else iter(['done'])
    def close(self): pass
    def reconfigure(self, sp=None, tools=None):
        if tools is not None: self.tools = {getattr(t, '__name__', ''): t for t in tools}

WRITES = {'create_file', 'replace_text', 'run_shell'}

@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'claude_native', lambda: True)
    monkeypatch.setattr('ramabana.agent.missing_runtime', lambda s: '')
    Native.made.clear(); Native.script, Native.hook = [], None
    a = Agent(MemHost({'/proj/a.py': 'def a(): pass\n'}), extensions=False, profile='full', cfg=tmp_path)
    a.routing.turn, a.routing.policy = CL.name, {}
    a.routing._cache[CL.name] = CL
    with use_chat(Native): yield a
    forget_forced_tags()

def test_the_turn_channel_is_opt_in_and_a_default_turn_passes_no_new_options(native):
    a = native
    assert a.ask('hi') == 'done'
    kw = Native.made[-1].kw
    assert 'tool_mode' not in kw and kw['effort'] == 'high' and Native.made[-1].calls[-1] == {}, 'the recording key holds'
    a.command('/model tools native')
    a.ask('again')
    assert Native.made[-1].kw['tool_mode'] == 'native' and Native.made[-1].hist[0]['content'].startswith('hi'), 'the conversation carried on'
    a.command('/model tools text')
    a.ask('once more')
    assert 'tool_mode' not in Native.made[-1].kw, 'text is the Claude default, so it is not passed'

def test_a_native_turn_keeps_steering_clipping_approvals_and_plan_mode(native):
    a = native
    a.set_tool_channel('native')
    from ramabana.agent import Approvals
    a.approvals = Approvals(mode='ask')
    Native.script = [('view_file', {'path': '/proj/a.py'})]
    Native.hook = lambda name: a.steer('look at the tests too')
    g = a.stream('go'); list(g)
    chat = Native.made[-1]
    tool_out = [m['content'] for m in chat.hist if m['role'] == 'tool'][0]
    assert chat.kw['tool_mode'] == 'native' and f'<user-message key="{a.inbox_key}">' in tool_out and 'look at the tests too' in tool_out
    assert chat.kw['tool_max_len'] == a.budget.tool_max and chat.kw['approve'] is not None, 'rishi clips and asks with what ramabana gives it'
    Native.hook = None
    a.set_plan_mode(True)
    a.ask('plan it')
    assert not WRITES & set(Native.made[-1].tools), 'plan mode withholds the write tools on the native channel too'

def test_a_native_turn_hands_back_a_structured_result(native):
    a = native
    a.set_tool_channel('native')
    Native.script = [('submit_result', {'result': {'n': 3}})]
    r = a.ask('how many?', schema={'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n']})
    assert r.result == {'n': 3} and Native.made[-1].kw['tool_mode'] == 'native'

def test_the_small_profile_on_the_native_channel_keeps_its_subset(native):
    a = native
    a.profile_choice = 'small'; a._tools = None
    a.set_tool_channel('native')
    a.ask('hi')
    names = set(Native.made[-1].tools)
    assert names and 'delegate_search' not in names and Native.made[-1].kw['tool_mode'] == 'native'

def test_a_read_only_sub_agent_on_the_native_channel_gets_no_write_tools(native):
    a = native
    a.subagent_settings(tools='native')
    Native.script = []
    dt = {t.__name__: t for t in a.tools}
    assert 'done' in dt['delegate_search'](['what is in a.py?'])
    sub = Native.made[-1]
    assert sub.kw['tool_mode'] == 'native' and not WRITES & set(sub.tools)

def test_turn_reasoning_reaches_claude_effort_per_call_and_auto_passes_none(native):
    a = native
    a.ask('hi', reasoning_effort='max')
    assert Native.made[-1].calls[-1] == {'effort': 'max'}
    a.ask('hi', reasoning_effort='auto')
    assert Native.made[-1].calls[-1] == {}, 'auto sends nothing, so rishi returns to the session effort'
    a.ask('hi', reasoning_effort='xhigh')
    assert Native.made[-1].calls[-1] == {'effort': 'xhigh'} and Native.made[-1].kw['effort'] == 'high', 'per call, nothing left on the chat'

def test_an_mcp_refusal_drops_to_text_once_and_says_so(native):
    a = native
    a.set_tool_channel('native')
    class Refused(Exception): pass
    real = Native.__call__
    def once(self, msg, stream=False, **kw):
        if self.kw.get('tool_mode') == 'native': raise Refused('You cannot dynamically configure MCP servers when an enterprise MCP config is present')
        return real(self, msg, stream, **kw)
    Native.__call__ = once
    try: assert a.ask('hi') == 'done'
    finally: Native.__call__ = real
    assert 'tool_mode' not in Native.made[-1].kw and core.native_support(CL) != 'native'
    assert a._be('turn').problems

def test_an_effort_refusal_is_retried_once_without_it_and_noted(monkeypatch):
    made = []
    class Picky(Native):
        def __call__(self, msg, stream=False, **kw):
            if self.kw.get('effort'): raise ValueError(f"invalid effort level {self.kw['effort']!r} for this model")
            return super().__call__(msg, stream, **kw)
    be = RishiBackend(CL, effort='max')
    with use_chat(Picky): out = be.send('hi')
    assert out == 'done' and be.fell_back == ['cl refused effort max; it ran at its default']
    class Dropping(Native):
        dropped_effort = 'openai/gpt-5.4 refused reasoning effort'
    be = RishiBackend(GPT, effort='xhigh')
    with use_chat(Dropping): be.send('hi')
    assert be.fell_back == ['gpt refused effort xhigh; it ran at its default'], "rishi's own retry is reported too"

def test_tab_completes_subagents_and_model_arguments():
    from ramabana.cli import arg_words
    assert 'effort' in arg_words('subagents', []) and arg_words('subagents', ['effort']) == ['default', 'low', 'medium', 'high', 'xhigh', 'max']
    assert arg_words('subagents', ['tools']) == ['native', 'text', 'auto'] and arg_words('subagents', ['tools', 'text']) == ['--save']
    assert arg_words('subagents', ['model'], ['gpt']) == ['default', 'gpt']
    assert arg_words('model', ['tools']) == ['native', 'text', 'auto'] and 'gpt' in arg_words('model', [], ['gpt'])

def test_config_set_writes_runtime_subagents_and_model_tables(tmp_path):
    from ramabana.setup import config_set, load_config
    p = tmp_path/'config.toml'
    config_set('runtime.tool_channel', 'text', p); config_set('subagents.effort', 'xhigh', p)
    config_set('model."openai/gpt-5.4".tool_channel', 'native', p); config_set('model.az.v1.effort', 'low', p)
    v = load_config(p)[0]
    assert v['runtime.tool_channel'] == 'text' and v['subagents.effort'] == 'xhigh'
    assert v['model'] == {'openai/gpt-5.4': {'tool_channel': 'native'}, 'az.v1': {'effort': 'low'}}
    for k, x in (('subagents.effort', 'huge'), ('nope.key', '1'), ('model.x.colour', 'red')):
        with pytest.raises(ValueError): config_set(k, x, p)

def test_every_tool_the_model_sees_describes_every_parameter(tmp_path):
    from urai import mk_toolspec
    from ramabana.agent import _result_tool, note_tools, plan_tools
    from ramabana.tools import status_tool
    a, _ = fake_agent(cfg=tmp_path)
    tools = [*a.tools, *note_tools(lambda *a, **k: ''), *plan_tools(list), status_tool(None), _result_tool({'type': 'object'}, {})]
    bare = [(f['name'], k) for f in (mk_toolspec(t)['function'] for t in tools) for k, v in f['parameters'].get('properties', {}).items() if not v.get('description')]
    assert not bare, bare

def test_a_default_remote_or_claude_chat_gets_no_new_options():
    assert not {'tool_mode', 'effort'} & set(RishiBackend(GPT)._runtime_kw())
    kw = RishiBackend(CL)._runtime_kw()
    assert 'tool_mode' not in kw and kw['effort'] == 'high'

# the review of caafd9c

def test_a_bad_effort_in_the_environment_is_reported_not_raised(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    monkeypatch.setenv('RAMABANA_SUBAGENT_EFFORT', 'huge')
    d = a.subagent_settings()
    assert d['ok'] and d['effort'] == '' and "'huge'" in d['note'] and 'ignored' in d['note']
    assert "'huge'" in a.command('/subagents')
    a._be_or_none = lambda job='turn': FakeBackend(GPT)
    assert a._sub_backend()[1] == {}, 'a delegation runs at the model default'

def test_a_local_runtime_reports_the_native_channel_it_really_uses(monkeypatch):
    assert core.tool_channel(GEMMA, session='text') == 'native'
    monkeypatch.setenv('RAMABANA_TOOL_CHANNEL', 'tags')
    assert core.tool_channel(GEMMA) == 'native' and core.tool_channel(GPT) == 'tags'
    assert core.native_support(GEMMA) == 'native'

def test_the_short_name_never_runs_another_model(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    a.routing.policy['subagent'] = 'openai/zz-sub-9'
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(core.AgentError) as e: a._named_backend('zz-sub-9')
    assert 'needs OPENAI_API_KEY' in str(e.value), 'not the fake backend the fallback route gives'
    monkeypatch.setenv('OPENAI_API_KEY', 'x')
    with use_chat(Native): b = a._named_backend('zz-sub-9')
    assert b.spec.model_id == 'openai/zz-sub-9'

def test_a_refused_per_turn_effort_keeps_the_chat_s_own():
    class Picky(Native):
        def __call__(self, msg, stream=False, **kw):
            if kw.get('effort') == 'max': raise ValueError("invalid effort level 'max' for this model")
            return super().__call__(msg, stream, **kw)
    Native.made.clear()
    be = RishiBackend(CL)
    with use_chat(Picky):
        assert be.send('hi', reasoning_effort='max') == 'done'
        assert be.fell_back == ['cl refused effort max; it ran at high'] and not be._no_effort
        assert Native.made[-1].kw['effort'] == 'high', "the constructor's effort is kept"
        be.send('again', reasoning_effort='max')
        assert Native.made[-1].calls[-1] == {} and len(be.fell_back) == 1, 'a refused level is not sent again'
    class Dropping(Native):
        dropped_effort = None
        def __call__(self, msg, stream=False, **kw):
            if kw.get('effort'): self.dropped_effort = 'refused'
            return super().__call__(msg, stream, **kw)
    be = RishiBackend(GPT)
    with use_chat(Dropping): be.send('hi', reasoning_effort='xhigh')
    assert be.fell_back == ['gpt refused effort xhigh; it ran at its default'] and be.chat.dropped_effort is None and not be._no_effort

def test_two_delegations_start_one_backend_for_one_model(tmp_path, monkeypatch):
    a, _ = fake_agent(cfg=tmp_path)
    a.routing._cache['gpt'] = GPT
    monkeypatch.setenv('OPENAI_API_KEY', 'x')
    made = []
    def slow(spec, **kw): time.sleep(.1); made.append(spec); return FakeBackend(spec)
    monkeypatch.setattr('ramabana.agent.make_backend', slow)
    ts = [threading.Thread(target=a._named_backend, args=('gpt',)) for _ in range(3)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(made) == 1

def test_save_writes_only_what_the_command_named(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_CONFIG', str(p := tmp_path/'config.toml'))
    monkeypatch.setenv('RAMABANA_SUBAGENT_EFFORT', 'low')
    a, _ = fake_agent(cfg=tmp_path)
    for cmd in ('--save', 'on --save', 'steps 30 --save'):
        assert 'nothing was saved' in a.subagents_command(cmd)['note'] and not p.exists(), cmd
    a.subagents_command('tools text --save')
    text = p.read_text()
    assert 'tool_channel = "tags"' in text and 'effort' not in text and '[jobs]' not in text
