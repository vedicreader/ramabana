"""Read-only access to complete history rows and durable memory."""
import json, os, subprocess, sys
from pathlib import Path

import pytest

from ramabana.agent import HISTORY_TAIL


def turn(sid, at, prompt, model='m', **changes):
    return {'session': sid, 'at': at, 'prompt': prompt, 'reply': 'ok', 'model': model, **changes}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_history_streams_all_complete_rows_and_changes_nothing(tmp_path):
    from ramabana.history import History

    details = tmp_path/'agent-details'/'s1.jsonl'
    details.parent.mkdir()
    details.write_text(json.dumps({'details': {'act1': 'whole result'}, 'prompt': 'whole prompt', 'turn_id': 't1'}) + '\n')
    rows = [
        turn('old', 1, 'older than the tail', reply='x' * (HISTORY_TAIL + 1)),
        turn('s1', 10, 'clipped', turn_id='t1', model='first', details='agent-details/s1.jsonl',
             activity=[{'id': 'act1', 'detail': 'clipped'}]),
        turn('s2', 20, 'second session', model='second'),
        turn('s1', 30, 'last s1', model='latest'),
    ]
    log = tmp_path/'agent-history.jsonl'
    log.write_bytes((json.dumps(rows[0]) + '\n[]\n').encode()
                    + b''.join((json.dumps(row) + '\n').encode() for row in rows[1:])
                    + json.dumps(turn('partial', 40, 'unfinished')).encode())
    (tmp_path/'agent-sessions.json').write_text(json.dumps({'sessions': {
        's1': {'title': 'My title', 'roots': ['/work/a']},
        's2': {'roots': '/not/a/list'},
        'ghost': {'title': 'Stale row', 'roots': ['/gone']},
    }}))

    memory = tmp_path/'memory'/'abc'/'MEMORY.md'
    agents = tmp_path/'learned'/'AGENTS.md'
    skill = tmp_path/'learned'/'skills'/'reader'/'SKILL.md'
    for n, (path, text) in enumerate(((memory, 'project note'), (agents, 'learned rule'), (skill, 'skill body')), 1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (100 + n, 100 + n))

    before = snapshot(tmp_path)
    history = History(tmp_path)
    sessions = history.sessions()
    assert [row['id'] for row in sessions] == ['s1', 's2', 'old']
    assert {key: sessions[0][key] for key in ('id', 'title', 'roots', 'turns', 'first_at', 'at', 'model')} == {
        'id': 's1', 'title': 'My title', 'roots': ['/work/a'], 'turns': 2,
        'first_at': 10.0, 'at': 30.0, 'model': 'latest'}
    assert history.sessions(since=20) == sessions[:2]
    assert history.sessions(limit=1) == sessions[:1]
    assert history.sessions(limit=0) == []
    with pytest.raises(ValueError): history.sessions(limit=-1)
    assert history.session_meta('s2') == sessions[1] and sessions[1]['roots'] == []
    assert history.session_meta('ghost') == {}

    turns = history.turns('s1')
    assert [row['at'] for row in turns] == [10, 30]
    assert turns[0]['prompt'] == 'whole prompt'
    assert turns[0]['activity'][0]['detail'] == 'whole result'
    assert history.turns('s1', limit=1) == [turns[-1]]
    assert history.turns('s1', limit=0) == []
    with pytest.raises(ValueError): history.turns('s1', limit=-1)
    assert history.turns('partial') == []

    docs = list(history.memory())
    assert [(ref, title, text) for ref, title, text, _ in docs] == [
        ('memory/abc', 'ramabana memory (abc)', 'project note'),
        ('learned/AGENTS.md', 'ramabana learned: AGENTS.md', 'learned rule'),
        ('learned/skills/reader', 'ramabana learned skill: reader', 'skill body'),
    ]
    assert [mtime for *_, mtime in docs] == [101, 102, 103]
    assert snapshot(tmp_path) == before


def test_history_groups_legacy_rows_and_uses_the_named_log(tmp_path):
    from ramabana.agent import LEGACY_GAP
    from ramabana.history import History

    rows = [turn(None, 1, 'first legacy'), turn(None, 2, 'same legacy'),
            turn(None, 2 + LEGACY_GAP + 1, 'next legacy')]
    (tmp_path/'other-history.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    history = History(tmp_path, 'other')
    assert [row['id'] for row in history.sessions()] == ['legacy-2', 'legacy-1']
    assert [row['prompt'] for row in history.turns('legacy-1')] == ['first legacy', 'same legacy']


def test_history_uses_the_config_folder_by_default(tmp_path, monkeypatch):
    from ramabana import setup
    from ramabana.history import History

    monkeypatch.setattr(setup, 'config_path', lambda: tmp_path/'config.toml')
    (tmp_path/'agent-history.jsonl').write_text(json.dumps(turn('s1', 1, 'hello')) + '\n')
    assert History().sessions()[0]['id'] == 's1'


def test_history_import_is_read_only_and_does_not_import_agent(tmp_path):
    home = tmp_path/'home'
    home.mkdir()
    code = r'''import json, pathlib, sys
home = pathlib.Path.home()
before = {str(p.relative_to(home)) for p in home.rglob('*')}
import ramabana.history
after = {str(p.relative_to(home)) for p in home.rglob('*')}
print(json.dumps({'created': sorted(after - before), 'agent': 'ramabana.agent' in sys.modules}))'''
    env = os.environ.copy()
    env['HOME'] = str(home)
    got = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parents[1], env=env,
                         text=True, capture_output=True, check=True)
    assert json.loads(got.stdout) == {'created': [], 'agent': False}


def test_history_confines_details_and_memory_to_config(tmp_path, monkeypatch):
    from ramabana.history import History
    from ramabana.history_core import hydrate_turns

    outside = tmp_path.parent/f'{tmp_path.name}-outside'
    outside.mkdir()
    (outside/'details.jsonl').write_text(json.dumps({'turn_id': 't1', 'prompt': 'escaped'}) + '\n')
    (tmp_path/'agent-details').symlink_to(outside, target_is_directory=True)
    row = {'turn_id': 't1', 'prompt': 'clipped', 'details': 'agent-details/details.jsonl'}
    assert hydrate_turns(tmp_path, [row])[0]['prompt'] == 'clipped'

    (outside/'MEMORY.md').write_text('escaped memory')
    (tmp_path/'memory').mkdir()
    (tmp_path/'memory'/'escape').symlink_to(outside, target_is_directory=True)
    learned = tmp_path/'learned'/'skills'
    learned.mkdir(parents=True)
    (learned/'escape').symlink_to(outside, target_is_directory=True)
    (learned/'broken').symlink_to(outside/'missing', target_is_directory=True)
    (learned/'directory'/'SKILL.md').mkdir(parents=True)
    denied = tmp_path/'memory'/'denied'/'MEMORY.md'
    denied.parent.mkdir()
    denied.write_text('unreadable')
    read_text = Path.read_text
    def guarded_read(path, *args, **kwargs):
        if path == denied: raise PermissionError(path)
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded_read)
    assert list(History(tmp_path).memory()) == []


def test_history_reads_no_log_index_or_details_a_link_leads_out_of_the_config_folder(tmp_path):
    from ramabana.history import History
    from ramabana.history_core import hydrate_turns

    cfg, outside = tmp_path/'cfg', tmp_path/'outside'
    cfg.mkdir(); outside.mkdir()
    (outside/'log.jsonl').write_text(json.dumps(turn('s', 1, 'escaped log')) + '\n')
    (outside/'index.json').write_text(json.dumps({'sessions': {'s': {'title': 'escaped title'}}}))
    (cfg/'agent-history.jsonl').symlink_to(outside/'log.jsonl')
    (cfg/'agent-sessions.json').symlink_to(outside/'index.json')
    assert History(cfg).sessions() == [] and History(cfg).turns('s') == []
    (cfg/'agent-history.jsonl').unlink()
    (cfg/'agent-history.jsonl').write_text(json.dumps(turn('s', 1, 'inside')) + '\n')
    assert History(cfg).sessions()[0]['title'] == 'inside', 'the linked index named the session'
    (tmp_path/'outside-history.jsonl').write_text(json.dumps(turn('o', 1, 'outside')) + '\n')
    for name in ('../outside', str(tmp_path/'outside'), 'a\0b'):
        assert History(cfg, name).sessions() == [] and History(cfg, name).turns('o') == [], name

    (cfg/'agent-details').mkdir()
    (cfg/'agent-details'/'s.jsonl').write_text(json.dumps({'turn_id': 't1', 'prompt': 'whole', 'details': {'a1': 'whole result'}}) + '\n')
    bad = [{'turn_id': 't1', 'prompt': 'clipped', 'details': ref} for ref in ('a\0b/c', 'agent-history.jsonl', '../outside/log.jsonl')]
    assert [t['prompt'] for t in hydrate_turns(cfg, bad)] == ['clipped'] * 3
    odd = [{'turn_id': ['t1'], 'details': 'agent-details/s.jsonl', 'activity': [{'id': ['a1']}, 'a1']},
           {'turn_id': 't1', 'details': 'agent-details/s.jsonl', 'activity': 'a1'}]
    got = hydrate_turns(cfg, odd)
    assert got[0]['activity'] == [{'id': ['a1']}, 'a1'] and got[1]['activity'] == 'a1' and got[1]['prompt'] == 'whole'


def test_history_skips_rows_with_nonnumeric_timestamps(tmp_path):
    from ramabana.history import History

    rows = [turn('bad', 'not-a-number', 'bad'), turn('good', 2, 'good'),
            turn(None, object.__name__, 'bad legacy'), turn(None, 3, 'good legacy'),
            turn('huge', 1 << 1100, 'huge'), turn('inf', float('inf'), 'inf'), turn('nan', float('nan'), 'nan')]
    (tmp_path/'agent-history.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows) + '5\n[1]\n' + '[' * 200_000 + ']' * 200_000 + '\n')
    history = History(tmp_path)
    assert [row['id'] for row in history.sessions()] == ['legacy-1', 'good']
    assert [row['prompt'] for row in history.turns('legacy-1')] == ['good legacy']


def test_the_agent_loads_a_log_with_scalar_rows(tmp_path):
    from ramabana.testing import fake_agent

    (tmp_path/'agent-history.jsonl').write_text(json.dumps(turn('s', 1, 'kept')) + '\n5\n"text"\nnull\n[1]\n')
    a, _ = fake_agent(cfg=tmp_path)
    assert [t['prompt'] for t in a.history] == ['kept']


def test_agent_reexports_history_core_names():
    import ramabana.agent as agent
    import ramabana.history_core as core

    for name in ('HISTORY_TAIL', 'HISTORY_TURNS', 'LEGACY_GAP', 'MAX_SPANS', '_log_turn',
                 'hydrate_turns', 'request_text', 'request_body', '_cut_title', 'request_title',
                 '_add_span', '_join_spans', '_set_spans', '_index_from_log', '_index_from_history'):
        assert getattr(agent, name) is getattr(core, name)
