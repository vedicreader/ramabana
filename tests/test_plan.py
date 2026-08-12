"""Session plans: durable todos for stop/start, briefing, and sub-agent-sized work."""
from pathlib import Path

from ramabana.agent import Agent, Plan, Todo, TODO_STATUSES, parse_plan_items, plan_tools
from ramabana.core import ModelSpec, Routing
from ramabana.testing import FakeBackend, MemHost, fake_agent
from ramabana.tools import NullHost


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


def test_plan_tools_and_slash_commands_share_one_object(tmp_path):
    a, _ = fake_agent()
    a.cfg = tmp_path
    names = {t.__name__: t for t in a.tools}
    assert names['set_plan']('Resume work', 'one\ntwo\nthree').startswith('**Resume work**')
    assert a.plan.progress() == (0, 3)
    out = names['update_todo'](a.plan.todos[0].id, status='active')
    assert a.plan.active().text == 'one' and 'active' in out
    assert 'one' in names['list_plan']()

    assert '**From slash**' in a.command('/plan From slash | a | b')
    assert a.command('/todo a done').count('[x]') == 1
    assert a.plan_path.exists()
    # survive a new Agent on the same session id (stop/start)
    a2, _ = fake_agent()
    a2.cfg, a2.session_id = tmp_path, a.session_id
    a2._load_plan()
    assert a2.plan.title == 'From slash' and a2.plan.find('a').status == 'done'


def test_the_briefing_carries_the_plan_so_a_resume_does_not_restart():
    a, _ = fake_agent()
    a.plan.set('Keep going', ['First', 'Second'])
    a.plan.update('First', status='active')
    sp = a.system_prompt()
    assert '## Current plan' in sp and 'First' in sp and 'resume from the active' in sp


def test_status_exposes_plan_for_leela_and_the_cli_bar():
    a, _ = fake_agent()
    assert a.status()['plan']['todos'] == [] and a.status()['plan_line'] == ''
    a.plan.set('P', ['x']); a.plan.update('x', status='active')
    s = a.status()
    assert s['plan']['title'] == 'P' and '▸' in s['plan_line']
    assert 'plan' in a.commands() and 'todo' in a.commands()


def test_parse_plan_items_accepts_newlines_and_json():
    assert parse_plan_items('a\n- b\n* c') == ['a', 'b', 'c']
    assert parse_plan_items('["x", "y"]') == ['x', 'y']
    assert parse_plan_items(['z', '']) == ['z']


def test_clearing_and_replacing_a_plan_is_what_stop_start_needs(tmp_path):
    "A cancelled turn must not invent todos; clearing must wipe the on-disk session plan too."
    a, _ = fake_agent()
    a.cfg = tmp_path
    a.command('/plan Dig | trench | plant')
    a.command('/todo trench active')
    assert a.plan_path.exists() and a.plan.active().text == 'trench'
    assert 'plan cleared' in a.command('/plan clear')
    assert not a.plan and a.plan_path.exists()  # empty plan still saved
    loaded = Plan.from_dict(__import__('json').loads(a.plan_path.read_text()))
    assert not loaded


def test_plan_tools_refuse_bad_status_without_corrupting_the_list():
    a, _ = fake_agent()
    tools = {t.__name__: t for t in plan_tools(lambda: a.plan, save=a._save_plan)}
    tools['set_plan']('T', '["only"]')
    tid = a.plan.todos[0].id
    assert 'ERROR' in tools['update_todo'](tid, status='finished')
    assert a.plan.todos[0].status == 'pending'
