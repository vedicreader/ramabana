import json, shutil
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pytest
from shalya.skills import Registry, check, load as load_mods

MOD = Path(__file__).parents[1] / 'examples/mods/checklist'


@pytest.fixture
def agent(tmp_path):
    learned = tmp_path / 'learned'
    learned.mkdir()
    (learned / 'checklist.md').write_text('# suggestions\n- update CHANGELOG\nnot an item\n- run slow tests\n')
    return SimpleNamespace(learned_dir=learned, home=tmp_path / 'checklist')


def load(agent):
    "A registry with the mod loaded from a copy of its folder, whose home holds `state.json`."
    if not agent.home.exists(): shutil.copytree(MOD, agent.home)
    reg = Registry(agent=agent)
    load_mods(reg, paths=[agent.home])
    assert reg.mods[0].on, reg.mods[0].note
    return reg


def load_in_memory(agent):
    reg = Registry(agent=agent)
    reg.add_mod('checklist', run_path(str(MOD / 'mod.py'))['setup'])
    return reg


def saved(agent): return json.loads((agent.home / 'state.json').read_text())['items']


def test_registration():
    result = check(MOD)
    assert result['mods'][0]['on'], result['mods'][0]['note']
    assert result['tools'] == ['checklist']
    assert 'ask the person' in result['tool_docs'][0]['doc']
    assert result['commands'] == ['check']
    assert len(result['status']) == 1
    assert result['hooks'] == {'before_turn': 1, 'before_tool': 1}


def test_commands_status_and_context(agent):
    reg = load(agent)
    cmd, status = reg.commands['check'][0], reg.status_segments[0]
    turn = lambda: reg.fire('before_turn', agent, 'go')[0]
    assert status(agent) is None and turn() is None
    for text in ('write docs', 'run tests', 'tag release'): cmd(agent, f'add {text}')
    assert 'already' in cmd(agent, 'add Write Docs')
    cmd(agent, 'done 1')
    cmd(agent, 'skip 2 no time')
    assert [(i['state'], i['reason']) for i in saved(agent)] == [('done', ''), ('skipped', 'no time'), ('open', '')]
    assert status(agent) == 'check 2/3'
    listing = cmd(agent, '')
    assert '[x]' in listing and '[-]' in listing and 'no time' in listing
    context = turn()['context']
    assert 'tag release' in context and 'write docs' not in context and 'run tests' not in context and 'checklist' in context
    cmd(agent, 'undo 2')
    assert saved(agent)[1]['state'] == 'open' and 'run tests' in turn()['context']
    assert 'no item' in cmd(agent, 'done 9')
    cmd(agent, 'clear')
    assert [i['text'] for i in saved(agent)] == ['run tests', 'tag release']
    cmd(agent, 'rm 1')
    assert [i['text'] for i in saved(agent)] == ['tag release']
    assert load(agent).status_segments[0](agent) == 'check 0/1'
    assert cmd(agent, 'bogus').startswith('Usage')


def test_tool(agent):
    reg = load(agent)
    tool = reg.tools[0]
    for text in ('write docs', 'run tests', 'tag release'): reg.commands['check'][0](agent, f'add {text}')
    assert tool('check', '2') == 'checked 2: run tests'
    assert tool('skip', 'TAG RELEASE', 'not today').startswith('skipped 3')
    assert tool('check', 'docs').startswith('checked 1')
    assert 'no open item' in tool('check', '2')
    assert 'unknown action' in tool('remove', '1')
    assert tool('add', 'bump version').startswith('added 4')
    assert [(i['state'], i['reason']) for i in saved(agent)] == [('done', ''), ('done', ''), ('skipped', 'not today'), ('open', '')]


def test_gating_items_belong_to_the_person(agent):
    reg = load(agent)
    cmd, tool = reg.commands['check'][0], reg.tools[0]
    cmd(agent, 'add! update CHANGELOG')
    for action in ('check', 'skip'):
        assert '/check done 1' in tool(action, 'CHANGELOG')
    assert saved(agent)[0]['state'] == 'open'
    cmd(agent, 'skip 1 later')
    assert saved(agent)[0]['state'] == 'skipped'
    cmd(agent, 'undo 1')
    cmd(agent, 'done 1')
    assert saved(agent)[0]['state'] == 'done'


def test_gate(agent):
    reg = load(agent)
    cmd = reg.commands['check'][0]
    gate = lambda name, **args: reg.fire('before_tool', agent, name, args)[0]
    cmd(agent, 'add plain item')
    assert gate('git_commit') is None
    cmd(agent, 'add! update CHANGELOG')
    assert gate('git_commit') == 'checklist: update CHANGELOG'
    assert gate('git_remote', op='push') == 'checklist: update CHANGELOG'
    assert gate('git_remote', op='fetch') is None and gate('git_remote', op='pull') is None and gate('git_remote') is None
    assert gate('run_shell') is None
    cmd(agent, 'done 2')
    assert gate('git_commit') is None
    assert cmd(agent, 'add! Plain Item').startswith('now gating')
    assert gate('git_commit') == 'checklist: plain item'

    corrupt = '{not json'
    (agent.home / 'state.json').write_text(corrupt)
    for name, args in [('git_commit', {}), ('git_remote', {'op': 'push'})]:
        assert gate(name, **args).startswith('checklist: the saved list cannot be read: ')
    assert gate('run_shell') is None
    shown = cmd(agent, '')
    assert 'cannot be read' in shown and str(agent.home / 'state.json') in shown and 'delete' in shown
    assert 'cannot be read' in cmd(agent, 'add another item')
    assert (agent.home / 'state.json').read_text() == corrupt
    (agent.home / 'state.json').unlink()
    assert gate('git_commit') is None


def test_suggest_pin_and_in_memory(agent):
    reg = load(agent)
    cmd = reg.commands['check'][0]
    suggested = cmd(agent, 'suggest')
    assert 'update CHANGELOG' in suggested and 'run slow tests' in suggested and 'not an item' not in suggested
    assert cmd(agent, 'pin 2').startswith('added 1')
    assert saved(agent)[0]['text'] == 'run slow tests'
    assert 'no suggestion' in cmd(agent, 'pin 5')
    off = SimpleNamespace(learned_dir=None)
    mem = load_in_memory(off)
    assert 'learning is off' in mem.commands['check'][0](off, 'suggest')
    mem.commands['check'][0](off, 'add in memory')
    assert mem.status_segments[0](off) == 'check 0/1'
    assert mem.mods[0].home is None
