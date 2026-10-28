"`ramabana setup peers`: show a diff, write only on yes, merge with the user's own config, remove only ours."
import json, shlex, subprocess, sys
from types import SimpleNamespace

import pytest

from ramabana import __version__
from ramabana.peer_hooks import hook_block
from ramabana.peers import Envelope, post
from ramabana.setup import Setup, setup_cli, setup_peers

THEIRS = {'matcher': '', 'hooks': [{'type': 'command', 'command': 'notify-me stop'}]}


def run(home, *argv, answer='y'):
    "Run `setup peers` on `home`; (code, output lines, prompts)."
    lines, asked = [], []
    def ask(q): asked.append(q); return answer
    code = setup_peers(list(argv), ask=ask, out=lines.append, home=home)
    return code, '\n'.join(lines), asked


def load(p): return json.loads(p.read_text())


def test_shows_diff_and_writes_on_yes(tmp_path):
    code, out, asked = run(tmp_path, '--agent', 'claude')
    assert code == 0 and asked == ['Write these changes? [y/N] ']
    assert f'--- {tmp_path}/.claude/settings.json (now)' in out and f'+++ {tmp_path}/.claude/settings.json (after)' in out
    assert '+    "SessionStart"' in out or '+  "hooks"' in out
    assert load(tmp_path/'.claude/settings.json')['hooks'] == hook_block('claude')
    sk = (tmp_path/'.claude/skills/peer-work/SKILL.md').read_text()
    assert sk.startswith('---\nname: peer-work\ndescription: ') and 'worker' in sk and not (tmp_path/'.codex').exists()


def test_no_answer_writes_nothing(tmp_path):
    for a in ('', 'n', 'no', 'maybe'):
        code, out, asked = run(tmp_path, answer=a)
        assert code == 1 and len(asked) == 2 and '+++' in out
    assert not (tmp_path/'.claude').exists() and not (tmp_path/'.codex').exists()


def test_yes_flag_does_not_ask(tmp_path):
    code, out, asked = run(tmp_path, '--yes')
    assert code == 0 and asked == [] and (tmp_path/'.claude/settings.json').exists() and (tmp_path/'.codex/hooks.json').exists()


def test_second_run_changes_nothing(tmp_path):
    run(tmp_path, '--yes')
    ps = [tmp_path/'.claude/settings.json', tmp_path/'.claude/skills/peer-work/SKILL.md', tmp_path/'.codex/hooks.json', tmp_path/'.codex/AGENTS.md']
    before = [p.read_text() for p in ps]
    code, out, asked = run(tmp_path)
    assert code == 0 and asked == [] and '+++' not in out and 'up to date' in out
    assert [p.read_text() for p in ps] == before


def test_keeps_users_other_hooks(tmp_path):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    mine = {'model': 'opus', 'hooks': {'Stop': [THEIRS, {'hooks': [{'type': 'command', 'command': 'ramabana peer-hook claude stop'}]}, THEIRS], 'Notification': [THEIRS]}}
    p.write_text(json.dumps(mine))
    run(tmp_path, '--agent', 'claude', '--yes')
    got = load(p)
    assert got['model'] == 'opus' and got['hooks']['Notification'] == [THEIRS]
    assert got['hooks']['Stop'] == [THEIRS, *hook_block('claude')['Stop'], THEIRS], 'ours replaced in place; the async waiter follows'
    assert got['hooks']['SessionStart'] == hook_block('claude')['SessionStart']


def test_remove_takes_only_ours(tmp_path):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    p.write_text(json.dumps({'model': 'opus', 'hooks': {'Stop': [THEIRS]}}))
    run(tmp_path, '--agent', 'claude', '--yes')
    assert len(load(p)['hooks']['Stop']) == 3
    code, out, _ = run(tmp_path, '--agent', 'claude', '--remove', '--yes')
    assert code == 0 and load(p) == {'model': 'opus', 'hooks': {'Stop': [THEIRS]}}
    assert not (tmp_path/'.claude/skills/peer-work/SKILL.md').exists()


def test_remove_drops_empty_events_and_hooks_key(tmp_path):
    run(tmp_path, '--agent', 'codex', '--yes')
    run(tmp_path, '--agent', 'codex', '--remove', '--yes')
    assert load(tmp_path/'.codex/hooks.json') == {} and not (tmp_path/'.codex/AGENTS.md').exists()


@pytest.mark.parametrize('text', ['{"hooks": ', '[]'])
def test_bad_json_refuses(tmp_path, text):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    p.write_text(text)
    code, out, asked = run(tmp_path, '--agent', 'claude', '--yes')
    assert code == 1 and str(p) in out and p.read_text() == text and not (tmp_path/'.claude/skills').exists()


def test_codex_writes_hooks_and_agents_md(tmp_path):
    mine = '# My rules\n\nBe brief.\n'
    (tmp_path/'.codex').mkdir()
    (tmp_path/'.codex/AGENTS.md').write_text(mine)
    code, out, _ = run(tmp_path, '--agent', 'codex')
    h = load(tmp_path/'.codex/hooks.json')
    assert code == 0 and h['hooks'] == hook_block('codex')
    a = (tmp_path/'.codex/AGENTS.md').read_text()
    assert a.startswith(mine) and a.count('<!-- ramabana peer-work start -->') == 1 and a.rstrip().endswith('<!-- ramabana peer-work end -->')
    assert 'trust' in out and not (tmp_path/'.claude').exists()
    run(tmp_path, '--agent', 'codex', '--yes')
    assert (tmp_path/'.codex/AGENTS.md').read_text() == a
    a2 = a.replace('worker', 'WORKER')
    (tmp_path/'.codex/AGENTS.md').write_text(a2 + '\nAfter.\n')
    run(tmp_path, '--agent', 'codex', '--yes')
    assert (tmp_path/'.codex/AGENTS.md').read_text() == a + '\nAfter.\n'
    run(tmp_path, '--agent', 'codex', '--remove', '--yes')
    assert (tmp_path/'.codex/AGENTS.md').read_text() == mine + '\nAfter.\n'


def test_doctor_reports_adapters(tmp_path, capsys):
    s = Setup(tmp_path/'cfg', environ={'HOME': str(tmp_path), 'PATH': '/bin'}, which=lambda n: None, system=lambda: 'Linux',
              run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=''), ask=lambda q: 'n', isatty=lambda: False)
    s.doctor()
    err = capsys.readouterr().out
    assert 'peers: claude hooks not installed: run ramabana setup peers --agent claude' in err and 'peers: codex hooks not installed' in err
    run(tmp_path, '--agent', 'claude', '--yes')
    s.doctor()
    err = capsys.readouterr().out
    assert f'peers: claude hooks installed (runs: {sys.executable}, ramabana {__version__})\n' in err and 'peers: codex hooks not installed: run ramabana setup peers --agent codex' in err


def test_setup_cli_hands_peers_on(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert setup_cli(['peers', '--agent', 'claude', '--yes'], out=lambda *_: None) == 0 and (tmp_path/'.claude/settings.json').exists()


def test_bad_arguments(tmp_path):
    with pytest.raises(SystemExit): run(tmp_path, '--agent', 'gemini')


def test_write_failure_keeps_the_original(tmp_path, monkeypatch):
    import os
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    p.write_text('{"model": "opus"}')
    monkeypatch.setattr(os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError): run(tmp_path, '--agent', 'claude', '--yes')
    assert p.read_text() == '{"model": "opus"}'


def test_equal_config_in_other_format_is_skipped(tmp_path):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    p.write_text(json.dumps({'hooks': hook_block('claude')}, indent=4))
    sk = tmp_path/'.claude/skills/peer-work/SKILL.md'; sk.parent.mkdir(parents=True)
    from ramabana.setup import peer_skill
    sk.write_text(peer_skill('claude'))
    code, out, asked = run(tmp_path, '--agent', 'claude')
    assert code == 0 and asked == [] and 'up to date' in out and p.read_text() == json.dumps({'hooks': hook_block('claude')}, indent=4)
    p.write_text('{"model":"opus"}')
    sk.unlink()
    code, out, asked = run(tmp_path, '--agent', 'claude', '--remove')
    assert asked == [] and 'up to date' in out and p.read_text() == '{"model":"opus"}'


def test_odd_hook_entries_are_not_ours(tmp_path):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    odd = {'Stop': ['text', {'hooks': 'x'}, {'hooks': [1, {'command': 5}]}]}
    p.write_text(json.dumps({'hooks': odd}))
    assert run(tmp_path, '--agent', 'claude', '--yes')[0] == 0
    assert load(p)['hooks']['Stop'][:3] == odd['Stop']
    run(tmp_path, '--agent', 'claude', '--remove', '--yes')
    assert load(p) == {'hooks': odd}


def test_setup_cli_takes_a_tuple(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert setup_cli(('peers', '--agent', 'codex', '--yes'), out=lambda *_: None) == 0 and (tmp_path/'.codex/hooks.json').exists()


def test_doctor_names_an_unreadable_config(tmp_path):
    from ramabana.setup import peers_status
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    p.write_text('{oops')
    assert peers_status(tmp_path)[0] == f'peers: claude config unreadable: {p}'


def commands(p): return [h['command'] for gs in load(p)['hooks'].values() for g in gs for h in g['hooks']]


def test_written_command_is_absolute_and_runs_without_path(tmp_path):
    run(tmp_path, '--yes')
    for p in (tmp_path/'.claude/settings.json', tmp_path/'.codex/hooks.json'):
        assert all(c.startswith(f'{shlex.quote(sys.executable)} -m ramabana.peer_hooks ') for c in commands(p))
    [stop] = [c for c in commands(tmp_path/'.claude/settings.json') if c.endswith(' claude stop')]
    peers = tmp_path/'peers'; peers.mkdir()
    post(peers, 'claude-s1', Envelope('note', 'v2 is out', {'key': 'ramabana-r1', 'name': 'leela'}))
    r = subprocess.run(['/bin/sh', '-c', stop], input=json.dumps({'session_id': 's1'}), capture_output=True, text=True, timeout=60,
                       env={'HOME': str(tmp_path), 'RAMABANA_PEERS': str(peers)})
    assert r.returncode == 0 and json.loads(r.stdout)['decision'] == 'block' and 'v2 is out' in r.stdout


def test_old_peer_hook_groups_are_replaced_and_removed(tmp_path):
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    old = lambda e: {'hooks': [{'type': 'command', 'command': f'ramabana peer-hook claude {e}'}]}
    p.write_text(json.dumps({'hooks': {'Stop': [THEIRS, old('stop'), old('wait')], 'SessionStart': [old('session-start')]}}))
    run(tmp_path, '--agent', 'claude', '--yes')
    assert not [c for c in commands(p) if 'peer-hook' in c] and load(p)['hooks']['Stop'][0] == THEIRS
    run(tmp_path, '--agent', 'claude', '--remove', '--yes')
    assert load(p)['hooks'] == {'Stop': [THEIRS]}


def test_doctor_reports_failing_hook_command(tmp_path):
    from ramabana.setup import peers_status
    p = tmp_path/'.claude/settings.json'; p.parent.mkdir()
    for cmd in ('ramabana peer-hook claude stop', '/no/such/python -m ramabana.peer_hooks claude stop'):
        p.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': cmd}]}]}}))
        line = peers_status(tmp_path)[0]
        assert line.startswith('peers: claude hook command fails: ') and line.endswith('; run ramabana setup peers --agent claude'), line


def test_doctor_names_a_ramabana_on_path_of_another_version(tmp_path, capsys):
    fake = tmp_path/'bin/ramabana'; fake.parent.mkdir()
    s = Setup(tmp_path/'cfg', environ={'HOME': str(tmp_path), 'PATH': '/bin'}, which=lambda n: fake if n == 'ramabana' else None, system=lambda: 'Linux',
              run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=''), ask=lambda q: 'n', isatty=lambda: False)
    fake.write_text('#!/bin/sh\necho 0.0.1\n'); fake.chmod(0o755)
    s.doctor()
    assert f'peers: ramabana on PATH ({fake}) is 0.0.1; the hooks run {__version__}. To fix it: uv tool upgrade ramabana\n' in capsys.readouterr().out
    fake.write_text(f'#!/bin/sh\necho {__version__}\n')
    s.doctor()
    assert 'ramabana on PATH' not in capsys.readouterr().out
