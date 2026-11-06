import json, shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from shalya.skills import Registry, check, load as load_mods

MOD = Path(__file__).parents[1] / 'examples/mods/decisions'


@pytest.fixture
def agent(tmp_path): return SimpleNamespace(session_id='s1', home=tmp_path / 'decisions', host=SimpleNamespace(roots=[tmp_path]))


def load(agent):
    "A registry with the mod loaded from a copy of its folder, whose home holds `state.json`."
    if not agent.home.exists(): shutil.copytree(MOD, agent.home)
    reg = Registry(agent=agent)
    load_mods(reg, paths=[agent.home])
    assert reg.mods[0].on, reg.mods[0].note
    return reg


def saved(agent, session='s1'): return json.loads((agent.home / 'state.json').read_text())['sessions'][session]


def test_registration():
    result = check(MOD)
    assert result['mods'][0]['on'], result['mods'][0]['note']
    assert result['tools'] == ['decision'] and result['commands'] == ['decide']
    assert result['sections'] == ['Needs your decision', 'Decide later', 'Build later', 'Decided']
    assert result['hooks'] == {'before_turn': 1} and len(result['status']) == 1


def test_log_sections_and_context(agent):
    reg = load(agent)
    cmd, tool, status = reg.commands['decide'][0], reg.tools[0], reg.status_segments[0]
    turn = lambda: reg.fire('before_turn', agent, 'go')[0]['context']
    assert reg.section_rows(agent) == [] and status(agent) is None and 'decision' in turn()
    assert tool('ask', 'Which database for the cache?').startswith('open 1')
    assert 'already open' in tool('ask', 'which DATABASE for the cache?')
    cmd(agent, '? Keep the old API')
    assert status(agent) == 'decide 2'
    assert tool('record', 'database', 'SQLite') == 'decided 1: Which database for the cache? -> SQLite'
    assert tool('record', 'Ship on Friday').startswith('decided 3')
    assert [(d['state'], d['choice']) for d in saved(agent)] == [('decided', 'SQLite'), ('open', ''), ('decided', '')]
    rows = {s['title']: s['rows'] for s in reg.section_rows(agent)}
    assert rows == {'Needs your decision': ['2. Keep the old API'], 'Decided': ['1. Which database for the cache? -> SQLite', '3. Ship on Friday']}
    context = turn()
    assert 'Keep the old API' in context and 'SQLite' in context
    assert 'no open question' in tool('record', '1', 'Postgres') and 'unknown action' in tool('rename', '2')
    cmd(agent, 'done 2 yes')
    cmd(agent, 'undo 1')
    assert [(d['state'], d['choice']) for d in saved(agent)] == [('open', ''), ('decided', 'yes'), ('decided', '')]
    cmd(agent, 'drop 3')
    assert 'no item' in cmd(agent, 'drop 9') and cmd(agent, 'done').startswith('Usage')
    assert cmd(agent, 'database').startswith('decided 4') and saved(agent)[0]['state'] == 'open'
    assert cmd(agent, 'clear the cache').startswith('decided 5') and cmd(agent, 'drop the old API').startswith('decided 6')
    for n in (6, 5, 4): cmd(agent, f'drop {n}')
    assert 'Keep the old API -> yes' in cmd(agent, '') and 'Keep the old API' in tool('list')
    other = SimpleNamespace(session_id='s2', home=agent.home, host=agent.host)
    assert reg.section_rows(other) == [] and status(agent) == 'decide 1'
    assert load(agent).section_rows(agent) == [dict(title='Needs your decision', rows=['1. Which database for the cache?'], style='yellow'),
                                               dict(title='Decided', rows=['2. Keep the old API -> yes'], style='green')]


def test_numbers_stay_and_the_agent_fixes_entries(agent):
    reg = load(agent)
    cmd, tool = reg.commands['decide'][0], reg.tools[0]
    rows = lambda: {s['title']: s['rows'] for s in reg.section_rows(agent)}
    tool('ask', 'SQLite or Postgres? and /decide Keep the old API')
    tool('ask', 'Expire after 1 day or 7 days?')
    tool('record', 'Keep the old API for now')
    assert tool('drop', '1').startswith('Needs your decision:\n2. Expire')
    assert rows() == {'Needs your decision': ['2. Expire after 1 day or 7 days?'], 'Decided': ['3. Keep the old API for now']}
    assert 'no item 1' in tool('drop', '1') and 'no open question 1' in tool('record', '1', 'SQLite')
    assert tool('record', '2', '7 days') == 'decided 2: Expire after 1 day or 7 days? -> 7 days'
    tool('reopen', '2')
    assert 'already open' in tool('reopen', '2') and 'nothing to edit' in tool('edit', '3')
    tool('edit', '3', text='Keep the old API for one release')
    tool('edit', '3', choice='until v2')
    cmd(agent, 'edit 2 Expire the cache after 1 day or 7 days?')
    assert 'is open' in tool('edit', '2', choice='7 days')
    assert rows() == {'Needs your decision': ['2. Expire the cache after 1 day or 7 days?'], 'Decided': ['3. Keep the old API for one release -> until v2']}
    assert '2. Expire the cache' in reg.fire('before_turn', agent, 'go')[0]['context']
    assert cmd(agent, 'clear') == 'cleared 1 decision(s)' and tool('ask', 'Ship on Friday?') == 'open 4: Ship on Friday?'
    assert [d['state'] for d in saved(agent)] == ['dropped', 'open', 'dropped', 'open']


def test_on_hold_outlives_the_session(agent):
    reg = load(agent)
    cmd, tool, status = reg.commands['decide'][0], reg.tools[0], reg.status_segments[0]
    rows = lambda who=agent: {s['title']: s['rows'] for s in reg.section_rows(who)}
    tool('ask', 'Swift window for the thin app?')
    tool('record', 'Build the thin Leela app', 'yes')
    tool('ask', 'Ship on Friday?')
    assert 'give the condition' in tool('park', '1')
    tool('park', '1', text='the thin-app build starts')
    cmd(agent, 'park 2 Leela 0.1.22 ships')
    held = {'Decide later': ['h1. Swift window for the thin app? · until the thin-app build starts'],
            'Build later': ['h2. Build the thin Leela app -> yes · until Leela 0.1.22 ships']}
    assert rows() == {'Needs your decision': ['3. Ship on Friday?'], **held}
    assert status(agent) == 'decide 1' and 'h1. Swift window' in reg.fire('before_turn', agent, 'go')[0]['context']
    later = SimpleNamespace(session_id='s2', home=agent.home, host=agent.host)
    elsewhere = SimpleNamespace(session_id='s3', home=agent.home, host=SimpleNamespace(roots=[agent.home]))
    assert rows(later) == held and rows(elsewhere) == {}
    assert cmd(agent, 'clear') == 'cleared 0 decision(s)' and 'until Leela' in tool('list')
    assert 'not on hold' in tool('resume', '3') and 'no item h9' in tool('resume', 'h9')
    cmd(later, 'resume h2')
    tool('record', 'h1', '7 days')
    assert rows() == {'Needs your decision': ['3. Ship on Friday?'], 'Decided': ['4. Swift window for the thin app? -> 7 days']}
    assert rows(later) == {'Decided': ['1. Build the thin Leela app -> yes']}
    data = json.loads((agent.home / 'state.json').read_text())
    data['sessions']['s1'][2]['at'] -= 2 * 3600
    (agent.home / 'state.json').write_text(json.dumps(data))
    cmd(agent, '')
    assert rows()['Needs your decision'] == ['3. Ship on Friday? · 2h']
