"`ramabana setup peers`: show a diff, write only on yes, merge with the user's own config, remove only ours."
import json
from types import SimpleNamespace

import pytest

from ramabana.peer_hooks import hook_block
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
    assert 'peers: claude hooks installed\n' in err and 'peers: codex hooks not installed: run ramabana setup peers --agent codex' in err


def test_setup_cli_hands_peers_on(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert setup_cli(['peers', '--agent', 'claude', '--yes'], out=lambda *_: None) == 0 and (tmp_path/'.claude/settings.json').exists()


def test_bad_arguments(tmp_path):
    with pytest.raises(SystemExit): run(tmp_path, '--agent', 'gemini')
