"""Tests for the agent harness.

Nothing here loads a model. What the harness is about is routing, approval, compaction
arithmetic, skill discovery, the activity stream and the tool wrappers, and a real engine
would put gigabytes and minutes in front of all of it while testing none of it.

These came across from leela's `tests/test_agent.py` when the harness moved out. The ones
that stayed behind are the ones that test the *binding* -- a `Workspace` answering `Host`,
an approval written into a notebook -- which is leela's half of the seam, not this one.

The notebooks in `nbs/` carry a `## Tests` section each as well. Those are written to be
read: they print what they checked. These are written to be run in bulk.
"""

import asyncio
import threading
import time

import pytest

from ramabana import agent, runtime, core, tools
from ramabana.runtime import Backend, Usage
from ramabana.agent import Agent
from ramabana.tools import Registry, load
from ramabana.tools import Host, NullHost
from ramabana.testing import FakeBackend, MemHost, fake_agent
from ramabana.tools import WRITE_TOOLS, tools_for


def test_ramabana_does_not_import_leela():
    """The seam that made the move a file move in the first place. It is still the rule:
    the harness may reach for fastcore, rishi, fastllm and aidialog, and for nothing that
    knows what an editor is."""
    import pathlib, re
    bad = []
    for p in (pathlib.Path(__file__).parent.parent/'ramabana').glob('*.py'):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.match(r'\s*(from|import)\s+leela', line): bad.append(f'{p.name}:{i}: {line.strip()}')
    assert not bad, 'ramabana must not import from leela:\n' + '\n'.join(bad)




def test_null_host_offers_only_what_it_supports():
    "A capability the host does not have must not become a tool the model keeps failing to call."
    names = {t.__name__ for t in tools_for(NullHost(['/x']))}
    assert 'search_code' in names and 'view_file' in names
    assert 'run_python' not in names and 'notebook_cells' not in names


def test_mem_host_gets_the_session_tools_it_supports():
    names = {t.__name__ for t in tools_for(MemHost())}
    assert 'run_python' not in names   # list_vars/terminal_text are still absent, so the group drops


def test_cheap_jobs_stay_local_when_the_turn_goes_to_the_cloud(monkeypatch):
    "The whole argument for routing: pointing the turn at a frontier model must not move completions."
    monkeypatch.delenv('LEELA_MODEL', raising=False)
    r = core.Routing(turn='gemma-e2b')
    r.set('gemma-12b')                       # stand-in for a cloud model, no network needed
    assert r.spec('turn').name == 'gemma-12b'
    expected = {'completion': core.DFLT_LOCAL, 'classify': core.DFLT_LOCAL,
                'summary': core.DFLT_LOCAL, 'subagent': core.DFLT_LOCAL}
    for job, name in expected.items():
        assert r.spec(job).name == name, job
        assert r.spec(job).local


def test_turn_model_change_keeps_the_conversation(monkeypatch):
    "A new Rishi backend starts lazily with the old backend's canonical history."
    made = []

    class SwitchBackend(FakeBackend):
        def close(self): self.chat = None

    def build(spec, **kw):
        backend = SwitchBackend(spec, replies=['continued'], **kw)
        made.append(backend)
        return backend

    monkeypatch.setattr(agent, 'make_backend', build)
    a = Agent(MemHost(), model='gemma-e2b', extensions=False, subagents=False)
    first = a.start()
    first.hist_.extend([{'role': 'user', 'content': 'remember cedar'},
                        {'role': 'assistant', 'content': 'I will remember cedar'}])

    a.set_model('gemma-12b')
    assert a.model.name == 'gemma-12b'
    assert not a.ready
    second = a.start()
    assert second is made[-1]
    assert second.hist == first.hist_
    assert second.hist is not first.hist_


def test_model_change_is_blocked_during_a_turn():
    a, _ = fake_agent()
    a.lock.acquire()
    try:
        with pytest.raises(RuntimeError, match='while the assistant is working'):
            a.set_model('gemma-12b')
    finally: a.lock.release()


def test_env_overrides_a_single_job(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r = core.Routing(turn='gemma-e2b')
    assert r.spec('summary').name == 'gemma-12b'
    assert r.spec('classify').name == core.DFLT_LOCAL


def test_unknown_bare_name_is_an_error_not_a_guess():
    "Silently running a typo on a frontier model is the kind of surprise that shows up on a bill."
    with pytest.raises(KeyError): core.resolve('sonnnet')


def test_a_vendor_slash_model_spec_is_taken_at_face_value():
    s = core.resolve('somevendor/some-model')
    assert (s.backend, s.model_id) == ('remote', 'somevendor/some-model')
    assert s.ctx > 0


def test_ungated_tools_run_without_asking():
    ap = agent.Approvals(tools={'edit_file'})
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})


def test_nothing_listening_refuses_immediately_rather_than_hanging():
    "A blocked worker thread is a hung IDE. Refusing fast is a bad answer that is at least an answer."
    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}})
    assert not d and time.time() - t0 < 1
    assert 'nothing is listening' in d.reply()


def test_a_refusal_carries_the_reason_back_to_the_model():
    "The point of the whole module: 'that file is generated' redirects, 'denied' just gets retried."
    ap = agent.Approvals(tools={'edit_file'}, timeout=5)
    stop = ap.listen()
    out = {}

    def answer():
        for _ in range(200):
            if (a := ap.pending) is not None:
                ap.answer(a.id, False, 'that file is generated, edit the notebook instead')
                return
            time.sleep(0.01)

    threading.Thread(target=answer, daemon=True).start()
    out['d'] = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'gen.py'}}})
    stop()
    assert not out['d']
    assert 'that file is generated' in out['d'].reply()


def test_an_approval_note_rides_back_with_the_result():
    ap = agent.Approvals(tools={'edit_file'}, mode='auto')
    d = ap.request('edit_file', {'path': 'a.py'})
    assert d and d.reply() is None          # nothing to say when it was simply approved
    d2 = agent.Ask(tool='edit_file').resolve(True, 'keep the docstring')
    assert 'keep the docstring' in d2.reply()


def test_every_watcher_and_the_recorder_both_hear_it():
    "A second frontend opening must not unhook the notebook recorder, or the first frontend."
    seen = []
    ap = agent.Approvals(tools={'edit_file'}, mode='auto', on_ask=lambda a: seen.append('recorder'))
    ap.listen(on_ask=lambda a: seen.append('one'))
    ap.listen(on_ask=lambda a: seen.append('two'))
    ap.mode = 'ask'

    def answer():
        for _ in range(200):
            if (a := ap.pending) is not None: return ap.answer(a.id, True)
            time.sleep(0.01)
    threading.Thread(target=answer, daemon=True).start()
    ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert sorted(seen) == ['one', 'recorder', 'two']


def test_preview_shows_what_would_change():
    p = agent.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = agent.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2


def test_cancelling_a_turn_releases_a_waiting_approval():
    ap = agent.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), ap.cancel_all()), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    stop()
    assert not d and 'cancelled' in d.reply()


def test_fastllm_patch_is_idempotent():
    "Hosted approvals reach rishi's own remote path now, so the shim is three functions saying so."
    from ramabana import agent
    assert agent.apply() and agent.apply() and agent.applied()


# What the four fastllm tests that used to live here were really about. They reached into
# `fastllm.chat._alite_call_func` and `AsyncChat.tcdict` -- a third-party private API which
# has since changed shape, so they failed against a library ramabana no longer patches. The
# behaviour they were protecting is this package's, and it is testable without one.
def test_the_gate_is_the_decision_a_backend_acts_on():
    "Both engines call `approve(tc)` and branch on the result, so it has to answer as a bool."
    ap = agent.Approvals(tools={'edit_file'}, mode='auto')
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': '{"path": "a.py"}'}})
    assert bool(d) and d.args == {'path': 'a.py'}
    assert bool(ap.gate({'function': {'name': 'search_code', 'arguments': {}}}))   # ungated: instant


def test_a_refusal_carries_its_reason_to_the_model():
    "The point of the gate: 'denied' teaches a model nothing, a reason changes its approach."
    ap = agent.Approvals(tools={'edit_file'}, mode='off')
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert not d and agent.DENIED in d.reply() and 'switched off' in d.reply()
    approved = agent.Ask(tool='edit_file').resolve(True, 'keep the docstring')
    assert approved.reply().endswith('keep the docstring')


def test_a_refusal_nobody_could_be_asked_about_still_reaches_the_recorder():
    "Otherwise it surfaces as a tool failure with the explanation nowhere in the UI."
    heard = []
    off = agent.Approvals(tools={'edit_file'}, mode='off', on_answer=heard.append)
    off.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    deaf = agent.Approvals(tools={'edit_file'}, on_answer=heard.append)   # nothing listening
    deaf.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    assert len(heard) == 2 and all(not a and a.note for a in heard)


def test_threshold_leaves_room_for_one_more_reply():
    assert runtime.threshold(200_000, 16_384) == 200_000 - 16_384
    assert runtime.threshold(0) is None
    assert runtime.should_compact(190_000, 200_000)
    assert not runtime.should_compact(100_000, 200_000)


def test_an_existing_summary_is_updated_not_re_summarised():
    "Summarising a summary loses a little every time; tau's second prompt exists to stop that."
    msgs = [{'role': 'user', 'content': runtime.SUMMARY_PREFIX + 'old summary'},
            {'role': 'assistant', 'content': 'later work'}]
    prev, rest = runtime.split_previous(msgs)
    assert prev == 'old summary' and len(rest) == 1
    p = runtime.summarise_prompt(msgs)
    assert '<previous-summary>' in p and 'PRESERVE' in p


def test_the_kept_tail_starts_at_a_user_turn():
    "A tail starting at an orphaned tool result is a dangling call some providers reject outright."
    c = runtime.Compactor(keep_recent=50)
    msgs = [{'role': 'user', 'content': 'a' * 400}, {'role': 'assistant', 'content': 'b'},
            {'role': 'tool', 'content': 'c'}, {'role': 'user', 'content': 'd'},
            {'role': 'assistant', 'content': 'e'}]
    kept = c._keep(msgs)
    assert kept and kept[0]['role'] == 'user'


def test_compaction_replaces_history_and_reorients(spec):
    be = FakeBackend(spec)
    be.start()
    be.hist_ = [{'role': 'user', 'content': 'x' * 4000}, {'role': 'assistant', 'content': 'y' * 4000},
                {'role': 'user', 'content': 'recent'}]
    c = runtime.Compactor(keep_recent=40)
    out = c.compact(be, lambda p, sp: 'GOAL: ship it')
    assert out == 'GOAL: ship it'
    head = be.hist[0]['content']
    assert head.startswith(runtime.SUMMARY_PREFIX) and 'GOAL: ship it' in head
    # the reorientation note is the aai-coding idea, and its value is in being specific
    assert 'kernel process was not touched' in head
    assert 'do not re-import' in head


def test_a_dead_kernel_is_not_promised():
    assert 'clean namespace' in runtime.reorient(kernel_alive=False)


def test_ramabana_profile_does_not_mix_in_aai_prompt_notices():
    a, be = fake_agent(replies=['done'])
    a.ask('add a test')
    assert runtime.ACTION_NOTICE not in str(be.sent[-1])


def test_saved_session_can_be_listed_and_resumed():
    a, backend = fake_agent()
    a.history = [
        {'session': 'agent_20260811-101010', 'at': 1, 'model': 'gemma-e4b',
         'prompt': 'remember cedar', 'reply': 'I will remember cedar'},
        {'session': 'agent_20260811-101010', 'at': 2, 'model': 'gemma-e4b',
         'prompt': 'what was it?', 'reply': 'cedar'},
    ]
    assert 'remember cedar' in a.command('/sessions')
    out = a.command('/resume latest')
    assert '2 turns' in out
    assert backend._resume_hist[-1] == {'role': 'assistant', 'content': 'cedar'}
    assert a.session_id == 'agent_20260811-101010'


def test_models_command_lists_local_and_cloud_choices(monkeypatch):
    a, _ = fake_agent()
    monkeypatch.setattr(agent, 'available_models', lambda include_legacy=False: [
        {'value': 'gemma-e4b', 'provider': 'litert', 'source': 'on device'},
        {'value': 'claude_code/claude-sonnet-4-6', 'provider': 'claude_code',
         'source': 'Claude Code login'},
    ])
    out = a.command('/models')
    assert 'gemma-e4b' in out
    assert 'claude_code/claude-sonnet-4-6' in out
    assert 'Claude Code login' in out
    assert 'models' in a.commands()


def test_aai_profile_remains_an_explicit_compatibility_option():
    a, be = fake_agent(replies=['done'], instruction_style='aai')
    a.ask('add a test')
    assert runtime.ACTION_NOTICE in str(be.sent[-1])


def test_prompt_notices_fire_where_they_should():
    assert runtime.prompt_notices('where is this handled?') == [runtime.Q_NOTICE]
    assert runtime.APPROVAL_NOTICE in runtime.prompt_notices('go')
    assert runtime.APPROVAL_NOTICE in runtime.prompt_notices('ok.')
    assert runtime.BTW_NOTICE in runtime.prompt_notices('BTW can you also check the tests')
    assert runtime.prompt_notices('add a test for this') == [runtime.ACTION_NOTICE]


def test_notices_ride_along_with_the_prompt():
    assert '<system-reminder>' in runtime.notices_block('what does this do?')
    assert runtime.ACTION_NOTICE in runtime.notices_block('add a test')


def test_pyskills_are_discovered_from_installed_packages():
    """The test of whether this feature is real rather than architectural: installing a
    package that publishes the entry point should hand the agent its skill, no code here."""
    found = {s.name: s for s in tools.discover()}
    assert 'exhash' in found, 'exhash ships the editing reference leela used to paste by hand'
    assert found['exhash'].source == 'pyskill'
    assert found['exhash'].text().strip()


def test_ramabana_publishes_answer_ai_coding_patterns_as_a_pyskill():
    found = {s.name: s for s in tools.discover()}
    skill = found['coding_patterns']
    assert skill.source == 'pyskill'
    assert skill.where == 'ramabana.coding_patterns'
    assert 'Every construct must earn its place' in skill.text()
    assert 'Ramabana workflow' in skill.text()


def test_skill_md_directories_win_over_packages(tmp_path):
    d = tmp_path/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: ours\n---\n\nlocal body\n')
    found = {s.name: s for s in tools.discover(cfg=tmp_path)}
    assert found['exhash'].source == 'md' and found['exhash'].description == 'ours'
    assert 'local body' in found['exhash'].text()


def test_a_bare_md_at_the_root_is_not_a_skill(tmp_path):
    d = tmp_path/'skills'
    d.mkdir(parents=True)
    (d/'loose.md').write_text('not a skill')
    assert not [s for s in tools.discover(cfg=tmp_path) if s.name == 'loose']


def test_the_index_carries_names_not_bodies():
    "Progressive disclosure: a dozen full skill texts would crowd out the code being worked on."
    ss = tools.discover()
    idx = tools.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    # The total scales with how many skills happen to be installed, so the invariant that
    # actually holds is per row: a name and one clipped line, never a body. `hf-cli` ships a
    # 1000-char frontmatter description, and without the clip one skill crowds out the rest.
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert len(rows) == len(ss)
    for r in rows: assert len(r) <= tools.SKILL_DESC_MAX + max(len(s.name) for s in ss) + 8


def test_find_refuses_to_guess_between_two_matches():
    from ramabana.tools import Skill, find
    ss = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(ss, 'edit') is None
    assert find(ss, 'editskill').name == 'editskill'


def test_frontmatter_parses_without_a_yaml_dependency():
    meta, body = tools.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'


def test_summaries_read_like_what_a_person_would_say():
    s = agent.summarise
    assert s('search_code', {'query': 'AgentSession'}) == 'Search AgentSession'
    assert s('view_file', {'path': 'leela/ai.py', 'start': 240, 'end': 290}) == 'View leela/ai.py:240-290'
    assert s('read_url', {'url': 'https://github.com/AnswerDotAI/ipymini'}).startswith('Web fetch: https://')
    assert s('edit_file', {'path': 'a.py'}) == 'Edit a.py'


def test_activity_fires_at_the_start_of_a_call_not_only_at_the_end():
    "Showing ⏳ while a fetch happens is the difference between looking alive and looking stuck."
    seen = []
    act = agent.Activity(on_change=lambda a: seen.append((a.summary, a.done)))
    a = act.start('read_url', {'url': 'https://x'})
    act.finish(a, 'the page')
    assert [d for _, d in seen] == [False, True]
    assert a.detail == 'the page' and a.done


def test_activity_markdown_folds_the_result():
    act = agent.Activity()
    act.mark()
    act.finish(act.start('search_code', {'query': 'q'}), 'a hit')
    md = act.md(mark=0)
    assert '<details>' in md and 'Search q' in md and 'a hit' in md


def test_a_fence_in_a_result_cannot_escape_the_fold():
    act = agent.Activity()
    a = act.start('view_file', {'path': 'a.md'})
    act.finish(a, 'text\n```\nfenced\n```\n')
    assert '\n```\n' not in a.md().split('```\n', 1)[1].rsplit('```', 1)[0]


def test_wrapping_a_tool_keeps_the_schema_the_model_reads():
    """Both backends build their tool schema from the signature and docstring, so the
    recorder must be transparent to `inspect` -- or every tool arrives as `(*args, **kw)`."""
    import inspect
    a, _ = fake_agent()
    t = next(t for t in a.tools if t.__name__ == 'view_file')
    assert t.__doc__ and 'lineno|hash|content' in t.__doc__
    assert list(inspect.signature(t).parameters) == ['path', 'start', 'end']


def test_changes_report_the_file_not_the_claim():
    "A tool that reported success and changed nothing must not appear in the diff."
    host = MemHost({'/proj/a.py': 'x = 1\n'})
    a, _ = fake_agent(host)
    create = next(t for t in a.tools if t.__name__ == 'create_file')
    a.before.clear()
    create(path='/proj/a.py', text='x = 1\n')          # writes the same bytes back
    assert a.changes() == {}
    create(path='/proj/a.py', text='x = 2\n')
    assert a.changes() == {'/proj/a.py': ('x = 1\n', 'x = 2\n')}


def test_a_turn_records_its_activity_and_usage():
    a, be = fake_agent(replies=['done'])
    assert a.ask('hello') == 'done'
    assert a.use.total == 15
    assert be.sent and 'hello' in str(be.sent[0])


def test_a_turn_is_charged_once():
    "A backend counts cumulatively, so adding its total every turn charges turn one twice."
    a, be = fake_agent(replies=['one', 'two', 'three'])
    for p in ('a', 'b', 'c'): a.ask(p)
    assert be.use.total == 45          # the backend's running total after three sends
    assert a.turn_use.total == 15      # this turn only
    assert a.use.total == 45           # the session, not 15 + 30 + 45


def test_a_failed_turn_does_not_inherit_the_last_turn_s_cost():
    a, be = fake_agent(replies=['fine'])
    a.ask('ok')
    assert a.turn_use.total == 15
    a._prepare('next')
    assert a.turn_use.total == 0


def test_a_question_gets_direct_routing_without_a_second_instruction_system():
    a, be = fake_agent(replies=['because x'])
    a.ask('why does this break?')
    sent = str(be.sent[0])
    assert 'route="direct"' in sent
    assert '<system-reminder>' not in sent


def test_write_tools_are_the_ones_approval_draws_its_line_around():
    # Not only the filesystem: deleting a standing reminder and spending money in a trolley are
    # both things a person should get to see before they happen.
    assert {'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
            'run_shell', 'memory_forget', 'create_skill', 'cancel_watch', 'cart_add',
            'cart_remove'} == set(WRITE_TOOLS)


def test_a_subagent_never_gets_a_write_tool():
    "A delegated question is a question. An agent nobody is watching should not be editing files."
    from ramabana.tools import read_only
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS)
    assert 'search_code' in names


def test_delegation_runs_on_a_thrown_away_conversation(spec):
    from ramabana.tools import delegate
    be = FakeBackend(spec)
    be.start()
    out = delegate(be, 'where do we do X?', tools=[])
    assert out == 'sub answer'
    assert len(be.spawned) == 1 and be.hist == []      # nothing leaked into the parent


def test_an_extension_registers_a_tool_a_skill_and_a_command(tmp_path):
    d = tmp_path/'extensions'
    d.mkdir(parents=True)
    (d/'mine.py').write_text(
        'def setup(ext):\n'
        '    @ext.tool\n'
        '    def count_todos(path: str) -> str:\n'
        '        "Count TODOs."\n'
        '        return "3"\n'
        '    ext.skill("house-style", "we write it like this", "How we write code here")\n'
        '    ext.command("hi", lambda agent, arg: f"hello {arg}", "say hi")\n')
    reg = load(Registry(), cfg=tmp_path)
    assert [t.__name__ for t in reg.tools] == ['count_todos']
    assert reg.skills[0].name == 'house-style'
    assert reg.commands['hi'][0](None, 'you') == 'hello you'
    assert 'mine.py: 1 tool(s), 1 skill(s), 1 command(s)' in reg.notes


def test_a_broken_extension_is_reported_not_raised(tmp_path):
    "An IDE that will not open because of a stray file in a config directory is a worse IDE."
    d = tmp_path/'extensions'
    d.mkdir(parents=True)
    (d/'bad.py').write_text('raise RuntimeError("boom")\n')
    reg = load(Registry(), cfg=tmp_path)
    assert reg.tools == [] and any('boom' in n for n in reg.notes)


def test_project_extensions_are_off_unless_asked_for(tmp_path):
    "A file in a repo you cloned five minutes ago runs arbitrary Python with the agent's tools."
    d = tmp_path/'.leela'/'extensions'
    d.mkdir(parents=True)
    (d/'x.py').write_text('def setup(ext):\n    ext.command("boom", lambda a, b: "", "")\n')
    assert load(Registry(), roots=[tmp_path]).commands == {}
    assert 'boom' in load(Registry(), roots=[tmp_path], project=True).commands


def test_an_unknown_hook_name_is_an_error():
    with pytest.raises(KeyError): Registry().on('after_lunch', lambda: None)


def test_commands_exist_once_for_both_frontends():
    a, _ = fake_agent()
    assert {'model', 'cost', 'compact', 'skills', 'tools', 'reload'} <= set(a.commands())
    assert a.command('nonsense') is None
    assert 'tok' in a.command('cost') or a.command('cost') is not None


def test_the_model_command_reports_the_whole_policy():
    a, _ = fake_agent()
    out = a.command('model')
    for job in core.JOBS: assert job in out


def test_usage_adds_up_across_models():
    u = Usage(model='a', input=1, output=2, total=3, cost=0.5) + Usage(model='b', input=1, output=1, total=2, cost=0.25)
    assert (u.total, u.cost, u.model) == (5, 0.75, 'b')
    assert '$0.75' in repr(u)


def test_a_stream_yields_before_it_finishes(spec):
    "The whole point. A stream that only yields at the end is a blocking call with extra steps."
    from ramabana.testing import ScriptedBackend, Step
    be = ScriptedBackend(steps=[Step(text='one two three')], token_delay=0)
    be.start()
    got = list(be.stream('hi'))
    assert len(got) == 3 and ''.join(got).split() == ['one', 'two', 'three']


def test_streaming_and_blocking_compose_the_same_message():
    "A streamed turn that quietly saw a different message would be a very hard bug to find."
    a, be = fake_agent(replies=['x', 'y'])
    a.ask_with('q', context='CTX', screen='SCR')
    blocking = str(be.sent[-1])
    list(a.stream_with('q', context='CTX', screen='SCR'))
    assert str(be.sent[-1]) == blocking
    assert '<notebook>' in blocking and '<screen>' in blocking


def test_a_streamed_turn_still_records_usage_and_activity():
    a, be = fake_agent(replies=['all done'])
    out = ''.join(a.stream('go'))
    assert out.strip() == 'all done'
    assert a.use.total == 15


def test_remote_reasoning_effort_is_applied_to_chat_not_passed_to_chat_call():
    from ramabana.runtime import RishiBackend
    spec = core.ModelSpec('cloud', 'remote', 'openai/gpt-test', ctx=1000)
    backend = RishiBackend(spec)
    class Chat:
        reasoning_effort = None
        def __call__(self, msg, **kw):
            assert 'reasoning_effort' not in kw
            return {'content': [{'type': 'text', 'text': 'ok'}]}
    backend.chat = Chat()
    assert backend._send('hello', reasoning_effort='high') == 'ok'
    assert backend.chat.reasoning_effort == 'high'


def test_surgical_compaction_keeps_questions_calls_results_and_both_text_ends():
    from ramabana.runtime import surgical_history, truncate_middle
    msgs = [
        {'role': 'user', 'content': 'first ' + 'middle ' * 100 + 'last'},
        {'role': 'assistant', 'content': 'I will inspect.', 'tool_calls': [
            {'function': {'name': 'view_file', 'arguments': {'path': 'a.py'}}}]},
        {'role': 'tool', 'content': 'line one\nline two'},
    ]
    text = surgical_history(msgs, {'user': 20, 'assistant': 20, 'call': 30, 'result': 20})
    assert text.startswith('§ first ') and 'last §' in text
    assert "▶ view_file(path='a.py')" in text
    assert '> line one ¶ line two' in text
    clipped = truncate_middle('begin ' + 'x ' * 200 + 'end', 12)
    assert clipped.startswith('begin ') and clipped.endswith('end')


def test_turns_have_stable_ids_and_model_context_can_fork_and_revise():
    a, be = fake_agent(replies=['first answer', 'branch answer'])
    assert a.ask('first question') == 'first answer'
    turn_id = a.history[-1]['turn_id']
    assert turn_id and a.history[-1]['branch_id'] == 'main'
    branch = a.revise(turn_id, 'user authored answer')
    assert branch['branch_id'].startswith('branch_')
    assert be.hist[-1]['content'] == 'user authored answer'
    assert a.ask('continue from revision') == 'branch answer'
    assert a.history[-1]['branch_id'] == branch['branch_id']


def test_a_subagent_can_ask_for_the_overlay_scope():
    """A sub-agent gets the scope choice too, because the sandbox is a limit on the Python
    available and not on what it is allowed to see — the overlay scope is protected by the
    AST policy rather than by an allowlist, so it is no more dangerous to delegate."""
    import inspect as _i
    from ramabana.tools import read_only

    class H(NullHost):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.calls = []
        def inspect_python(self, code, scope='isolated'):
            self.calls.append((code, scope))
            return 'ok'
        def list_vars(self): return 'df: DataFrame'
        def terminal_text(self, lines=200): return ''
        def run_python(self, code): return 'ok'

    h = H(['/x'])
    tools = tools_for(h)
    sub = {t.__name__: t for t in read_only(tools)}
    assert 'inspect_python' in sub
    assert 'scope' in _i.signature(sub['inspect_python']).parameters
    sub['inspect_python'](code='list(df.columns)', scope='overlay')
    assert h.calls == [('list(df.columns)', 'overlay')]


def test_a_narrow_host_says_why_rather_than_failing_silently():
    from ramabana.tools import NullHost as _N

    class H(_N):
        scopes = ('isolated',)
        def inspect_python(self, code, scope='isolated'):
            if scope not in self.scopes: return f'scope {scope!r} is not available here'
            return 'sandboxed ok'
    assert 'not available' in H(['/x']).inspect_python('x', 'overlay')


# -- reading outside the open folders ----------------------------------------
# The sandbox has two halves and only one of them was ever the point. Confining *writes* is
# what stops an agent damaging something nobody opened; confining *reads* is what stops it
# answering a question whose answer is in a sibling checkout. `read_outside` separates them.


def _outside_host(tmp_path):
    from ramabana.tools import LocalHost
    root, sibling = tmp_path/'proj', tmp_path/'sibling'
    (root/'pkg').mkdir(parents=True)
    (root/'pkg'/'a.py').write_text('def a(): return 1\n')
    sibling.mkdir()
    (sibling/'notes.md').write_text('the answer is 42\n')
    return LocalHost([root], web=False, index=False, read_outside=True), root, sibling


def test_a_read_outside_the_folders_is_off_until_it_is_asked_for(tmp_path):
    from ramabana.tools import LocalHost
    open_host, root, sibling = _outside_host(tmp_path)
    shut = LocalHost([root], web=False, index=False)
    assert shut.read(sibling/'notes.md') is None
    assert open_host.read(sibling/'notes.md').strip() == 'the answer is 42'


def test_reading_outside_does_not_make_writing_outside(tmp_path):
    open_host, root, sibling = _outside_host(tmp_path)
    with pytest.raises(core.AgentError, match='outside the open folders'):
        open_host.check(sibling/'notes.md')
    with pytest.raises(core.AgentError, match='outside the open folders'):
        open_host.write(sibling/'notes.md', 'no')
    assert (sibling/'notes.md').read_text().strip() == 'the answer is 42'


def test_reading_outside_never_opens_credentials(tmp_path):
    "Opening the sandbox is a decision about source, not about the user's keys."
    open_host, root, sibling = _outside_host(tmp_path)
    (sibling/'.env').write_text('OPENAI_API_KEY=sk-real\n')
    with pytest.raises(core.AgentError, match='credentials'):
        open_host.check(sibling/'.env', reading=True)
    assert open_host.read(sibling/'.env') is None
    assert tools.denied('/home/k/.ssh/id_rsa') and not tools.denied(root/'pkg'/'a.py')


def test_enumeration_stays_inside_even_when_reads_do_not(tmp_path):
    "A read outside is always a path the model already knew; it can never be found by walking."
    open_host, root, sibling = _outside_host(tmp_path)
    assert all(str(root) in str(p) for p in open_host.walk())
    listed = {t.__name__: t for t in tools_for(open_host)}['list_files']('notes.md')
    assert 'sibling' not in listed


def test_a_read_only_tool_reaches_outside_and_a_write_tool_does_not(tmp_path):
    open_host, root, sibling = _outside_host(tmp_path)
    ts = {t.__name__: t for t in tools_for(open_host)}
    assert 'the answer is 42' in ts['view_file'](str(sibling/'notes.md'))
    assert tools.failed(ts['create_file'](str(sibling/'new.py'), 'x = 1'))
    assert not (sibling/'new.py').exists()


def test_readable_does_not_send_the_flag_to_a_host_that_predates_it():
    "The flag is a host capability, not a tool assumption: an older host sees its own call."
    from pathlib import Path as _P
    seen = []

    class OldHost(NullHost):
        def check(self, path, must_exist=False):
            seen.append((path, must_exist))
            return _P(path)

    assert not tools._takes_reading(OldHost)
    assert str(tools.readable(OldHost(['/proj']), '/anywhere/x.py')) == '/anywhere/x.py'
    assert seen == [('/anywhere/x.py', False)]


# -- what a turn actually sends ----------------------------------------------


def test_an_attached_image_survives_the_tool_plan():
    """`compose` returns a list of content parts when an image is attached, and `list += str`
    extends it one character at a time -- so the plan, the preflight evidence and any
    requested skill used to arrive as several hundred single-character parts."""
    a, be = fake_agent(replies=['a screenshot of a traceback'])
    a.local_multimodal = True
    a.ask(a.compose('what is in this image?', image=b'\x89PNG-not-really'))
    sent = be.sent[-1]
    assert isinstance(sent, list) and len(sent) == 2
    assert sent[0] == b'\x89PNG-not-really'
    assert '<user-request>' in sent[1] and '<tool-plan' in sent[1]


def test_checkpoints_do_not_grow_without_bound():
    "Each one is a deep copy of a whole conversation, so an unbounded dict of them is a leak."
    a, be = fake_agent(replies=['ok'] * 30)
    for i in range(agent.MAX_CHECKPOINTS + 5): a.ask(f'turn {i}')
    assert len(a.checkpoints) == agent.MAX_CHECKPOINTS
    assert a.current_turn_id in a.checkpoints


def test_the_feed_names_the_command_a_shell_call_ran():
    "`run_shell` is the tool a person most wants to read back, and it had no summary at all."
    assert agent.summarise('run_shell', {'command': 'pytest -q'}) == 'Run pytest -q'
    assert agent.Act(tool='run_shell').kind == 'run'
    assert agent.summarise('grep', {'pattern': 'RESERVE', 'path_filter': 'tests/'}) == 'Grep RESERVE in tests/'
    assert agent.summarise('list_watches', {'due_only': False}) == 'List watches'


def test_native_capture_follows_the_application_env_prefix():
    "`use_env_prefix` exists so one hard-coded variable name is not wrong in every other app."
    import os
    from ramabana.runtime import captured
    core.use_env_prefix('RAMABANA_', 'LEELA_')
    os.environ['RAMABANA_NO_NATIVE_CAPTURE'] = '1'
    try: assert captured().enabled is False
    finally: os.environ.pop('RAMABANA_NO_NATIVE_CAPTURE', None)
    assert captured().enabled is True


# -- the fossick binding ------------------------------------------------------


def test_web_search_asks_fossick_for_as_many_results_as_it_wants(monkeypatch):
    "fossick's own default is 10, so slicing twenty down to twenty quietly returned ten."
    from ramabana.tools import LocalHost
    import fossick
    asked = {}

    def search(q, **kw):
        asked.update(q=q, **kw)
        return [{'title': f'r{i}', 'href': f'https://x/{i}'} for i in range(kw.get('n', 10))]

    monkeypatch.setattr(fossick, 'search', search)
    host = LocalHost(['.'], web=True, index=False)
    assert len(host.web_search('nbdev export', n=20)) == 20 and asked['n'] == 20


def test_research_hands_over_the_digest_rather_than_the_whole_record(monkeypatch):
    "`{query, sources, digest, dropped}` stringified sent the same markdown twice, in dict syntax."
    from ramabana.tools import LocalHost
    import fossick
    monkeypatch.setattr(fossick, 'research', lambda q, **kw: {
        'query': q, 'sources': [{'title': 't', 'href': 'https://x', 'md': 'body'}],
        'digest': '## t\nhttps://x\n\nbody', 'dropped': []})
    out = LocalHost(['.'], web=True, index=False).research('what is nbdev')
    assert out == '## t\nhttps://x\n\nbody' and 'dropped' not in out
