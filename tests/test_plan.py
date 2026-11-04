"""Session plans: durable todos for stop/start, briefing, and sub-agent-sized work."""
from ramabana.agent import Plan, plan_tools
from ramabana.testing import fake_agent


def test_a_plan_tracks_progress_and_keeps_one_active_step():
    p = Plan('Ship', ['Design', 'Wire', 'Test'])
    assert p.progress() == (0, 3)
    p.update('Design', status='active')
    assert p.active().text == 'Design'
    p.update('Wire', status='active')
    assert p.active().text == 'Wire'
    assert p.find('Design').status == 'pending'   # only one active
    p.update('Wire', status='done', note='merged')
    assert p.progress() == (1, 3)


def test_plan_tools_refuse_bad_status_without_corrupting_the_list():
    a, _ = fake_agent()
    tools = {t.__name__: t for t in plan_tools(lambda: a.plan, save=a._save_plan)}
    tools['set_plan'](['only'])
    tid = a.plan.todos[0].id
    assert 'ERROR' in tools['update_todo'](tid, status='finished')
    assert a.plan.todos[0].status == 'pending'


def test_the_ledger_records_each_request_and_a_resumed_session_reads_it_first(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, replies=['planned', 'ok', 'sure'])
    a.ask('Build the handout with an Answers panel')
    a.ask('go')
    a.ask('Then add folder links')
    assert [(r.id, r.status) for r in a.plan.requests] == [('r1', 'agreed'), ('r2', 'open')]
    a.release_session()
    b, be = fake_agent(cfg=tmp_path, replies=['back'])
    b.resume_session(a.session_id, keep_model=True)
    b.ask('where were we?')
    assert '<session-ledger>' in be.sent[0] and 'Then add folder links' in be.sent[0], 'the first prompt after a resume carries the ledger'
    b.ask('next')
    assert '<session-ledger>' not in be.sent[1], 'the ledger goes out once'


def test_done_needs_a_commit_that_is_in_the_repo_or_a_file_that_exists(tmp_path):
    import subprocess
    from shalya.host import LocalHost
    git = lambda *a: subprocess.run(['git', *a], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q', '-b', 'main'); git('config', 'user.email', 't@t'); git('config', 'user.name', 't')
    (tmp_path/'a.txt').write_text('hi\n'); git('add', 'a.txt'); git('commit', '-q', '-m', 'init')
    a, _ = fake_agent(host=LocalHost([str(tmp_path)], index=False))
    a.plan.set('', ['commit', 'write', 'test'])
    tool = {t.__name__: t for t in a.tools}['update_todo']
    out = tool('commit', 'done', evidence='deadbee1')
    assert 'ERROR' in out and 'commit deadbee1 is not in' in out and a.plan.find('commit').status == 'pending'
    assert 'ERROR' not in tool('commit', 'done', evidence=git('rev-parse', '--short', 'HEAD'))
    assert 'missing.txt was not found' in tool('write', 'done', evidence='missing.txt')
    assert 'ERROR' not in tool('write', 'done', evidence='a.txt')
    shot = tmp_path.parent/'shot.png'; shot.write_bytes(b'')   # outside the open folder, as screenshots under /tmp are
    a.plan.add('screenshot', id='shot')
    assert 'ERROR' not in tool('shot', 'done', evidence=str(shot)), 'an absolute path that exists counts anywhere'
    assert 'ERROR' not in tool('test', 'done', evidence='pytest -q: 3 passed'), 'a command and its result are checked by shape'


def test_a_sub_agent_cannot_mark_a_step_of_the_parent_plan_done():
    a, _ = fake_agent(subagents=True, subagent_writes=True)
    assert 'update_todo' in {t.__name__ for t in a.tools}
    for tools in (a._sub_plain(), a._sub_tools()):
        assert not {'set_plan', 'update_todo'} & {getattr(t, '__name__', '') for t in tools}
