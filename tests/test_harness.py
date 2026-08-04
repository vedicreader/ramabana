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

from ramabana import activity, compact, hitl, models, skills
from ramabana.backend import Backend, Usage
from ramabana.chat import Agent
from ramabana.extensions import Registry, load
from ramabana.host import Host, NullHost
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
    r = models.Routing(turn='gemma-e2b')
    r.set('gemma-12b')                       # stand-in for a cloud model, no network needed
    assert r.spec('turn').name == 'gemma-12b'
    for job in ('completion', 'classify', 'summary', 'subagent'):
        assert r.spec(job).name == models.DFLT_LOCAL, job
        assert r.spec(job).local


def test_env_overrides_a_single_job(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL_SUMMARY', 'gemma-12b')
    r = models.Routing(turn='gemma-e2b')
    assert r.spec('summary').name == 'gemma-12b'
    assert r.spec('classify').name == 'gemma-e2b'


def test_unknown_bare_name_is_an_error_not_a_guess():
    "Silently running a typo on a frontier model is the kind of surprise that shows up on a bill."
    with pytest.raises(KeyError): models.resolve('sonnnet')


def test_a_vendor_slash_model_spec_is_taken_at_face_value():
    s = models.resolve('somevendor/some-model')
    assert (s.backend, s.model_id) == ('fastllm', 'somevendor/some-model')
    assert s.ctx > 0


def test_ungated_tools_run_without_asking():
    ap = hitl.Approvals(tools={'edit_file'})
    assert ap.gate({'function': {'name': 'search_code', 'arguments': {'query': 'x'}}})


def test_nothing_listening_refuses_immediately_rather_than_hanging():
    "A blocked worker thread is a hung IDE. Refusing fast is a bad answer that is at least an answer."
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    t0 = time.time()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}})
    assert not d and time.time() - t0 < 1
    assert 'nothing is listening' in d.reply()


def test_a_refusal_carries_the_reason_back_to_the_model():
    "The point of the whole module: 'that file is generated' redirects, 'denied' just gets retried."
    ap = hitl.Approvals(tools={'edit_file'}, timeout=5)
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
    ap = hitl.Approvals(tools={'edit_file'}, mode='auto')
    d = ap.request('edit_file', {'path': 'a.py'})
    assert d and d.reply() is None          # nothing to say when it was simply approved
    d2 = hitl.Ask(tool='edit_file').resolve(True, 'keep the docstring')
    assert 'keep the docstring' in d2.reply()


def test_every_watcher_and_the_recorder_both_hear_it():
    "A second frontend opening must not unhook the notebook recorder, or the first frontend."
    seen = []
    ap = hitl.Approvals(tools={'edit_file'}, mode='auto', on_ask=lambda a: seen.append('recorder'))
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
    p = hitl.preview_for('edit_file', {'path': 'a.py', 'commands': '[["12|ab|","s","old","new"]]'})
    assert '12|ab|' in p and 'old' in p and 'new' in p
    p2 = hitl.preview_for('create_file', {'path': 'b.py', 'text': 'x = 1'})
    assert 'new file' in p2 and 'x = 1' in p2


def test_cancelling_a_turn_releases_a_waiting_approval():
    ap = hitl.Approvals(tools={'edit_file'}, timeout=30)
    stop = ap.listen()
    threading.Thread(target=lambda: (time.sleep(0.05), ap.cancel_all()), daemon=True).start()
    d = ap.gate({'function': {'name': 'edit_file', 'arguments': {}}})
    stop()
    assert not d and 'cancelled' in d.reply()


def _fl():
    fastllm = pytest.importorskip('fastllm.chat')
    from ramabana import fastllm_hitl
    assert fastllm_hitl.apply(), fastllm_hitl.note()
    return fastllm


def hello(name: str) -> str:
    "Say hello to someone."
    return f'hi {name}'


def _call(approve=None):
    fc = _fl()
    from aidialog.msg_parts import ToolCall
    from fastllm.chat import lite_mk_func
    from toolslm.funccall import mk_ns
    tc = ToolCall(id='1', name='hello', arguments={'name': 'x'})
    return asyncio.run(fc._alite_call_func(tc, [lite_mk_func(hello)], mk_ns([hello]), approve=approve))


def test_fastllm_patch_is_idempotent():
    from ramabana import fastllm_hitl
    assert fastllm_hitl.apply() and fastllm_hitl.apply() and fastllm_hitl.applied()


def test_fastllm_runs_the_tool_when_nothing_gates_it():
    assert _call() == 'hi x'


def test_fastllm_refuses_a_gated_tool_and_says_why():
    out = _call(approve=hitl.Approvals(tools={'hello'}, mode='off').gate)
    assert hitl.DENIED in out and 'switched off' in out


def test_fastllm_carries_an_approval_note_back():
    ap = hitl.Approvals(tools={'hello'}, mode='auto')
    ap.on_answer = None
    out = _call(approve=lambda tc: hitl.Ask(tool='hello').resolve(True, 'be careful'))
    assert 'hi x' in out and 'be careful' in out


def test_fastllm_tcdict_carries_the_policy_per_chat():
    "Per chat, not a module global: a sub-agent must not inherit the main conversation's prompt."
    fc = _fl()
    c = fc.AsyncChat.__new__(fc.AsyncChat)
    c.tool_schemas, c.ns, c.approve = [], {}, 'POLICY'
    assert c.tcdict['approve'] == 'POLICY'


def test_threshold_leaves_room_for_one_more_reply():
    assert compact.threshold(200_000, 16_384) == 200_000 - 16_384
    assert compact.threshold(0) is None
    assert compact.should_compact(190_000, 200_000)
    assert not compact.should_compact(100_000, 200_000)


def test_an_existing_summary_is_updated_not_re_summarised():
    "Summarising a summary loses a little every time; tau's second prompt exists to stop that."
    msgs = [{'role': 'user', 'content': compact.SUMMARY_PREFIX + 'old summary'},
            {'role': 'assistant', 'content': 'later work'}]
    prev, rest = compact.split_previous(msgs)
    assert prev == 'old summary' and len(rest) == 1
    p = compact.summarise_prompt(msgs)
    assert '<previous-summary>' in p and 'PRESERVE' in p


def test_the_kept_tail_starts_at_a_user_turn():
    "A tail starting at an orphaned tool result is a dangling call some providers reject outright."
    c = compact.Compactor(keep_recent=50)
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
    c = compact.Compactor(keep_recent=40)
    out = c.compact(be, lambda p, sp: 'GOAL: ship it')
    assert out == 'GOAL: ship it'
    head = be.hist[0]['content']
    assert head.startswith(compact.SUMMARY_PREFIX) and 'GOAL: ship it' in head
    # the reorientation note is the aai-coding idea, and its value is in being specific
    assert 'kernel process was not touched' in head
    assert 'do not re-import' in head


def test_a_dead_kernel_is_not_promised():
    assert 'clean namespace' in compact.reorient(kernel_alive=False)


def test_prompt_notices_fire_where_they_should():
    assert compact.prompt_notices('where is this handled?') == [compact.Q_NOTICE]
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('go')
    assert compact.APPROVAL_NOTICE in compact.prompt_notices('ok.')
    assert compact.BTW_NOTICE in compact.prompt_notices('BTW can you also check the tests')
    assert compact.prompt_notices('add a test for this') == []


def test_notices_ride_along_with_the_prompt():
    assert '<system-reminder>' in compact.notices_block('what does this do?')
    assert compact.notices_block('add a test') == ''


def test_pyskills_are_discovered_from_installed_packages():
    """The test of whether this feature is real rather than architectural: installing a
    package that publishes the entry point should hand the agent its skill, no code here."""
    found = {s.name: s for s in skills.discover()}
    assert 'exhash' in found, 'exhash ships the editing reference leela used to paste by hand'
    assert found['exhash'].source == 'pyskill'
    assert found['exhash'].text().strip()


def test_skill_md_directories_win_over_packages(tmp_path):
    d = tmp_path/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: ours\n---\n\nlocal body\n')
    found = {s.name: s for s in skills.discover(cfg=tmp_path)}
    assert found['exhash'].source == 'md' and found['exhash'].description == 'ours'
    assert 'local body' in found['exhash'].text()


def test_a_bare_md_at_the_root_is_not_a_skill(tmp_path):
    d = tmp_path/'skills'
    d.mkdir(parents=True)
    (d/'loose.md').write_text('not a skill')
    assert not [s for s in skills.discover(cfg=tmp_path) if s.name == 'loose']


def test_the_index_carries_names_not_bodies():
    "Progressive disclosure: a dozen full skill texts would crowd out the code being worked on."
    ss = skills.discover()
    idx = skills.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    assert len(idx) < 4000


def test_find_refuses_to_guess_between_two_matches():
    from ramabana.skills import Skill, find
    ss = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(ss, 'edit') is None
    assert find(ss, 'editskill').name == 'editskill'


def test_frontmatter_parses_without_a_yaml_dependency():
    meta, body = skills.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'


def test_summaries_read_like_what_a_person_would_say():
    s = activity.summarise
    assert s('search_code', {'query': 'AgentSession'}) == 'Search AgentSession'
    assert s('view_file', {'path': 'leela/ai.py', 'start': 240, 'end': 290}) == 'View leela/ai.py:240-290'
    assert s('read_url', {'url': 'https://github.com/AnswerDotAI/ipymini'}).startswith('Web fetch: https://')
    assert s('edit_file', {'path': 'a.py'}) == 'Edit a.py'


def test_activity_fires_at_the_start_of_a_call_not_only_at_the_end():
    "Showing ⏳ while a fetch happens is the difference between looking alive and looking stuck."
    seen = []
    act = activity.Activity(on_change=lambda a: seen.append((a.summary, a.done)))
    a = act.start('read_url', {'url': 'https://x'})
    act.finish(a, 'the page')
    assert [d for _, d in seen] == [False, True]
    assert a.detail == 'the page' and a.done


def test_activity_markdown_folds_the_result():
    act = activity.Activity()
    act.mark()
    act.finish(act.start('search_code', {'query': 'q'}), 'a hit')
    md = act.md(mark=0)
    assert '<details>' in md and 'Search q' in md and 'a hit' in md


def test_a_fence_in_a_result_cannot_escape_the_fold():
    act = activity.Activity()
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


def test_a_question_gets_the_answer_first_notice():
    a, be = fake_agent(replies=['because x'])
    a.ask('why does this break?')
    assert '<system-reminder>' in str(be.sent[0]) and 'question' in str(be.sent[0])


def test_write_tools_are_the_ones_approval_draws_its_line_around():
    assert {'edit_file', 'create_file', 'edit_cell', 'add_cell', 'run_python'} == set(WRITE_TOOLS)


def test_a_subagent_never_gets_a_write_tool():
    "A delegated question is a question. An agent nobody is watching should not be editing files."
    from ramabana.subagent import read_only
    a, _ = fake_agent()
    names = {t.__name__ for t in read_only(a.tools)}
    assert not (names & WRITE_TOOLS)
    assert 'search_code' in names


def test_delegation_runs_on_a_thrown_away_conversation(spec):
    from ramabana.subagent import delegate
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
    for job in models.JOBS: assert job in out


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


def test_a_subagent_can_ask_for_the_overlay_scope():
    """A sub-agent gets the scope choice too, because the sandbox is a limit on the Python
    available and not on what it is allowed to see — the overlay scope is protected by the
    AST policy rather than by an allowlist, so it is no more dangerous to delegate."""
    import inspect as _i
    from ramabana.subagent import read_only

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
    from ramabana.host import NullHost as _N

    class H(_N):
        scopes = ('isolated',)
        def inspect_python(self, code, scope='isolated'):
            if scope not in self.scopes: return f'scope {scope!r} is not available here'
            return 'sandboxed ok'
    assert 'not available' in H(['/x']).inspect_python('x', 'overlay')
