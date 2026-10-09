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
    assert '[▸]' in p.md() or '[x]' in p.md()
    assert p.line().startswith('1/3')


def test_plan_tools_refuse_bad_status_without_corrupting_the_list():
    a, _ = fake_agent()
    tools = {t.__name__: t for t in plan_tools(lambda: a.plan, save=a._save_plan)}
    tools['set_plan'](['only'])
    tid = a.plan.todos[0].id
    assert 'ERROR' in tools['update_todo'](tid, status='finished')
    assert a.plan.todos[0].status == 'pending'
