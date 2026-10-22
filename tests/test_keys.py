"Owner-only keys, dotenv round-trips, and environment precedence."

import os
import stat
import subprocess

import pytest

from ramabana.setup import keys_path, load_keys, save_key


def test_keys(monkeypatch, capsys):
    names = ('RB_KEY_ONE', 'RB_KEY_TWO', 'RB_COMMAND', 'RB_FAILED', 'RB_LITERAL')
    for name in names:
        monkeypatch.setenv(name, '')
        monkeypatch.delenv(name)
    p = keys_path()
    value = "a 'quote', a \\slash, ${NOT_EXPANDED}\nand another line"
    assert save_key(names[0], value) == p
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert os.environ[names[0]] == value
    first = p.read_text()
    p.write_text('# keep this comment\n' + first)
    save_key(names[1], 'second')
    assert first in p.read_text()
    save_key(names[0], 'replacement')
    assert p.read_text().count(names[0] + '=') == 1
    assert '# keep this comment\n' in p.read_text()
    save_key(names[0], value)
    for name in names[:2]: monkeypatch.delenv(name)
    monkeypatch.setenv(names[1], 'from environment')
    assert load_keys() == [names[0]]
    assert os.environ[names[0]] == value
    assert os.environ[names[1]] == 'from environment'

    with p.open('a') as f: f.write(f"{names[2]}='!printf abc'\n{names[3]}='!false'\n")   # a command is written by hand
    save_key(names[4], '!typed')
    monkeypatch.delenv(names[4])
    assert set(load_keys()) == {names[2], names[4]}
    assert os.environ[names[2]] == 'abc'
    assert os.environ[names[4]] == '!typed', 'a key typed into /login is text, never a command'
    assert names[3] not in os.environ
    assert capsys.readouterr().err.splitlines() == [f'{names[3]}: key command failed or returned no output']

    for name in names: monkeypatch.delenv(name, raising=False)
    p.chmod(0o644)
    assert load_keys() == []
    assert all(name not in os.environ for name in names)
    assert f'chmod 600 {p}' in capsys.readouterr().err
    save_key(names[0], 'private again')
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    with pytest.raises(ValueError): save_key('INVALID-NAME', 'unused')


def test_key_command_failures(monkeypatch, capsys):
    name = 'RB_COMMAND_FAILURE'
    monkeypatch.setenv(name, '')
    monkeypatch.delenv(name)
    p = keys_path()
    p.write_text(f'{name}=!secret command\n')
    p.chmod(0o600)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('secret command', 30)
    monkeypatch.setattr(subprocess, 'run', timeout)
    assert load_keys() == []
    assert name not in os.environ
    assert capsys.readouterr().err.splitlines() == [f'{name}: key command failed or returned no output']
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, ' \n', 'secret error'))
    assert load_keys() == []
    assert name not in os.environ
    assert capsys.readouterr().err.splitlines() == [f'{name}: key command failed or returned no output']


def test_beat_keys(monkeypatch, capsys):
    from ramabana.monitor import beat_env_path, load_beat_env
    names = ('RB_BEAT_SHARED', 'RB_BEAT_ONLY', 'RB_KEYS_ONLY')
    for name in names:
        monkeypatch.setenv(name, '')
        monkeypatch.delenv(name)
    p = keys_path()
    p.write_text(f'{names[0]}=keys\n{names[2]}=keys only\n')
    p.chmod(0o600)
    beat = beat_env_path()
    beat.write_text(f'{names[0]}=beat\n{names[1]}=beat only\n')
    beat.chmod(0o600)
    assert load_beat_env() == list(names[:2])
    assert [os.environ[n] for n in names] == ['beat', 'beat only', 'keys only']
    for name in names: monkeypatch.delenv(name)
    beat.chmod(0o644)
    assert load_beat_env() == []
    assert os.environ[names[0]] == 'keys'
    assert names[1] not in os.environ
    assert f'chmod 600 {beat}' in capsys.readouterr().err
    for name in names: monkeypatch.delenv(name, raising=False)
    beat.unlink()
    assert load_beat_env() == []
    assert os.environ[names[2]] == 'keys only'
