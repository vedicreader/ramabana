"A stopped or crashed job comes back with everything its tools returned, not only the text of its turns."
from ramabana import agent
from ramabana.testing import FakeBackend, MemHost, fake_agent

LONG = 'x' * 5000


def test_a_full_resume_restores_whole_tool_results_and_a_plain_one_stays_text(tmp_path):
    plain, _ = fake_agent(cfg=tmp_path/'plain'); plain.ask('hello')
    assert not (plain.runs_dir/agent.HIST).exists(), 'only an agent that keeps its conversation pays to save it'
    a, be = fake_agent(cfg=tmp_path, keep_conversation=True)
    a.ask('read the long file')
    be.hist_.append({'role': 'tool', 'content': LONG})   # what a tool returned during the turn
    a.ask('summarise it')
    a.release_session()
    b, be2 = fake_agent(cfg=tmp_path)
    b.resume_session(a.session_id, keep_model=True, full=True)
    assert any(m.get('content') == LONG for m in be2.snapshot_hist()), 'the tool result comes back whole'
    b.release_session()
    c, be3 = fake_agent(cfg=tmp_path)
    c.resume_session(a.session_id, keep_model=True)
    assert not any(m.get('content') == LONG for m in be3.snapshot_hist()), 'a plain resume is unchanged: turns as text'


def test_a_saved_conversation_is_used_only_for_its_model_and_ends_on_a_whole_exchange(tmp_path):
    import json
    from ramabana.agent import _whole
    a, be = fake_agent(cfg=tmp_path, keep_conversation=True)
    a.ask('read the long file')
    be.hist_.append({'role': 'tool', 'content': LONG}); a.ask('again')
    saved = json.loads((a.runs_dir/agent.HIST).read_text())
    (a.runs_dir/agent.HIST).write_text(json.dumps(saved | {'model_id': 'another-model'}))
    a.release_session()
    b, be2 = fake_agent(cfg=tmp_path)
    b.resume_session(a.session_id, keep_model=True, full=True)
    assert not any(m.get('content') == LONG for m in be2.snapshot_hist()), "another model's messages are not replayed into this one"
    user = {'role': 'user', 'content': 'go'}
    call = {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'view_file', 'arguments': {}}}]}
    result = {'role': 'tool', 'tool_call_id': 'c1', 'content': 'text'}
    assert _whole([user, call]) == [user], 'a call a stop left without its result is dropped'
    assert _whole([user, call, result]) == [user, call, result]


def test_a_stop_that_leaves_its_backend_running_hands_the_conversation_on(monkeypatch):
    "A run that did not stop in its grace is detached and its backend dropped; the next turn started from nothing."
    monkeypatch.setattr(agent, 'make_backend', lambda spec, **kw: FakeBackend(spec, **kw))
    a = agent.Agent(MemHost(), extensions=False, subagents=False)
    old = a._be('turn'); old.start()
    old.hist_.extend([{'role': 'user', 'content': 'adapt the Isha Upanishad'}, {'role': 'tool', 'content': LONG}])
    run = a._new_run('adapt it')
    run.backend, run.state = old, 'detached'
    a._release_run(run)
    new = a._be('turn')
    assert new is not old and new.snapshot_hist() == old.snapshot_hist()
