"First run: ramabana relaunches itself in its own tmux server, offers to install tmux, and `--doctor` reports."
from types import SimpleNamespace

import pytest

from ramabana.setup import Setup, tmux_conf, tmux_version


class Box:
    "The fake machine: programs on PATH, the commands run, the prompts shown and the exec made."
    def __init__(self, have=('tmux',), version='tmux 3.5a', system='Darwin', answer='', code=0, ext='on'):
        self.have, self.version, self.system, self.answer, self.code, self.ext = set(have), version, system, answer, code, ext
        self.calls, self.asked, self.execd = [], [], None
    def which(self, name): return f'/bin/{name}' if name in self.have else None
    def run(self, cmd, **kw):
        self.calls.append(list(cmd))
        if cmd[1:] == ['-V']: return SimpleNamespace(returncode=0, stdout=self.version + '\n')
        if cmd[1:] == ['show', '-sv', 'extended-keys']: return SimpleNamespace(returncode=0 if self.ext else 1, stdout=f'{self.ext}\n')
        if 'install' in cmd and self.code == 0: self.have.add('tmux')
        return SimpleNamespace(returncode=self.code if 'install' in cmd else 0, stdout='')
    def ask(self, q):
        self.asked.append(q)
        return self.answer
    def execvpe(self, *a): self.execd = a

def script(tmp_path):
    "An executable `ramabana` script, as a console entry point installs."
    p = tmp_path/'bin'/'ramabana'
    p.parent.mkdir(exist_ok=True)
    p.write_text('#!/bin/sh\n')
    p.chmod(0o755)
    return str(p)

def mk(tmp_path, box=None, environ=None, tty=True, argv=None):
    box, argv = box or Box(), argv or (script(tmp_path), '--model', 'x')
    s = Setup(tmp_path/'cfg', environ={'HOME': '/h', 'PATH': '/bin'} if environ is None else environ, argv=list(argv),
              cwd='/work', which=box.which, system=lambda: box.system, run=box.run, execvpe=box.execvpe,
              ask=box.ask, isatty=lambda: tty)
    return s, box

def test_the_conf_turns_on_the_keys_its_tmux_knows_and_is_written_only_when_it_changes(tmp_path):
    assert (tmux_version('tmux 3.5a'), tmux_version('tmux next-3.6'), tmux_version('tmux 3.0')) == ((3, 5), (3, 6), (3, 0))
    new, mid, old = tmux_conf((3, 5)), tmux_conf((3, 4)), tmux_conf((3, 1))
    assert 'extended-keys on' in new and 'extended-keys-format csi-u' in new
    assert 'extended-keys on' in mid and 'csi-u' not in mid
    assert 'extended-keys' not in old
    for line in ('escape-time 10', 'mouse on', 'status off', 'remain-on-exit off', 'default-terminal', 'RGB'): assert line in old
    s, box = mk(tmp_path)
    p = s.conf()
    assert p == tmp_path/'cfg'/'tmux.conf' and p.read_text() == new
    p.touch()
    import os
    os.utime(p, (0, 0))
    s.conf()
    assert p.stat().st_mtime == 0
    box.version = 'tmux 3.4'
    assert s.conf().read_text() == mid and p.stat().st_mtime > 0

def test_the_relaunch_execs_tmux_on_its_own_server_with_the_same_args_cwd_and_a_wrapped_flag(tmp_path):
    s, box = mk(tmp_path, environ={'HOME': '/h', 'PATH': '/bin', 'OPENAI_API_KEY': 'k'})
    s.launch()
    exe, argv, env = box.execd
    assert exe == '/bin/tmux'
    assert argv[:5] == ['tmux', '-L', 'ramabana', '-f', str(tmp_path/'cfg'/'tmux.conf')]
    i = argv.index('new-session')
    assert argv[i-1] == ';' and argv[5:8] == ['set', '-g', 'update-environment']
    assert set(argv[8].split()) == {'HOME', 'PATH', 'OPENAI_API_KEY', 'RAMABANA_WRAPPED'}
    assert argv[i+1] == '-s' and argv[i+2].startswith('ramabana-') and argv[i+3:i+5] == ['-c', '/work']
    assert argv[i+5:i+7] == ['sh', '-c'] and argv[-3:] == [script(tmp_path), '--model', 'x']
    assert env == {'HOME': '/h', 'PATH': '/bin', 'OPENAI_API_KEY': 'k', 'RAMABANA_WRAPPED': '1'}
    assert (tmp_path/'cfg'/'tmux.conf').exists()
    s2, box2 = mk(tmp_path)
    s2.launch()
    assert box2.execd[1][i+2] != argv[i+2]

def test_without_a_script_on_argv_the_relaunch_runs_this_python(tmp_path):
    import sys
    s, box = mk(tmp_path, argv=('-c', '--pane', 'on'))
    s.launch()
    cmd = box.execd[1][-5:]
    assert cmd[:2] == [sys.executable, '-c'] and 'ramabana.cli' in cmd[2] and cmd[-2:] == ['--pane', 'on']

@pytest.mark.parametrize('why,kw,environ,tty', [
    ('one-shot', dict(prompt='hi'), None, True),
    ('json', dict(as_json=True), None, True),
    ('not a tty', {}, None, False),
    ('already in tmux', {}, {'TMUX': '/tmp/tmux-1/default,1,0'}, True),
    ('--tmux off', dict(tmux='off'), None, True),
    ('RAMABANA_TMUX=off', {}, {'RAMABANA_TMUX': 'off'}, True),
    ('wrapped', {}, {'RAMABANA_WRAPPED': '1'}, True),
])
def test_no_relaunch_when(tmp_path, why, kw, environ, tty):
    s, box = mk(tmp_path, environ=environ, tty=tty)
    s.launch(**kw)
    assert box.execd is None and box.asked == [] and not (tmp_path/'cfg'/'tmux.conf').exists()

def test_the_relaunch_needs_tmux_3_but_not_the_split_version(tmp_path):
    s, box = mk(tmp_path, Box(version='tmux 3.0a'))
    s.launch(tmux='on')
    assert box.execd is not None and 'extended-keys' not in (tmp_path/'cfg'/'tmux.conf').read_text()
    s, box = mk(tmp_path, Box(version='tmux 2.9'))
    s.launch()
    assert box.execd is None
    s, box = mk(tmp_path, Box(version=''))
    s.launch()
    assert box.execd is None

@pytest.mark.parametrize('system,have,cmd', [
    ('Darwin', {'brew'}, ['brew', 'install', 'tmux']),
    ('Linux', {'apt-get', 'dnf', 'sudo'}, ['sudo', 'apt-get', 'install', '-y', 'tmux']),
    ('Linux', {'dnf', 'sudo'}, ['sudo', 'dnf', 'install', '-y', 'tmux']),
])
def test_yes_installs_tmux_with_the_named_command_then_relaunches(tmp_path, system, have, cmd):
    s, box = mk(tmp_path, Box(have=have, system=system, answer='y'))
    s.launch()
    assert len(box.asked) == 1 and ' '.join(cmd) in box.asked[0] and '[y/N]' in box.asked[0]
    assert cmd in box.calls and box.execd is not None

@pytest.mark.parametrize('system,have', [('Darwin', set()), ('Linux', {'sudo'}), ('Windows', set())])
def test_without_an_installer_nothing_is_asked_and_the_hint_prints_once(tmp_path, capsys, system, have):
    s, box = mk(tmp_path, Box(have=have, system=system))
    s.launch()
    assert box.asked == [] and box.execd is None and '--doctor' in capsys.readouterr().err
    s.launch()
    assert capsys.readouterr().err == ''

def test_no_is_remembered_and_only_doctor_asks_again(tmp_path, capsys):
    s, box = mk(tmp_path, Box(have={'brew'}, answer='n'))
    s.launch()
    assert len(box.asked) == 1 and box.execd is None and '--doctor' in capsys.readouterr().err
    assert ['brew', 'install', 'tmux'] not in box.calls
    s2, box2 = mk(tmp_path, Box(have={'brew'}, answer='y'))
    s2.launch()
    assert box2.asked == [] and box2.execd is None
    assert s2.doctor() == 0 and len(box2.asked) == 1 and ['brew', 'install', 'tmux'] in box2.calls

def test_a_failed_install_continues_without_tmux(tmp_path, capsys):
    s, box = mk(tmp_path, Box(have={'brew'}, answer='y', code=1))
    s.launch()
    assert ['brew', 'install', 'tmux'] in box.calls and box.execd is None and '--doctor' in capsys.readouterr().err
    s2, box2 = mk(tmp_path, Box(have={'brew'}, answer='y', code=1))
    s2.launch()
    assert box2.asked == []

def test_inside_your_own_tmux_extended_keys_are_turned_on_only_when_off(tmp_path, capsys):
    inside = {'TMUX': '/tmp/tmux-1/default,1,0'}
    s, box = mk(tmp_path, Box(ext='off'), environ=inside)
    s.launch()
    assert ['/bin/tmux', 'set', '-s', 'extended-keys', 'on'] in box.calls and 'extended-keys' in capsys.readouterr().err
    for ext in ('on', 'always', ''):
        s, box = mk(tmp_path, Box(ext=ext), environ=inside)
        s.launch()
        assert not any('set' in c for c in box.calls) and box.execd is None
    s, box = mk(tmp_path, Box(ext='off'), environ=inside)
    s.launch(prompt='hi')
    assert box.calls == []

def test_doctor_prints_one_line_per_check(tmp_path, capsys):
    s, box = mk(tmp_path, Box(have={'tmux', 'ramabana-pane'}, version='tmux 3.0a'))
    assert s.doctor() == 0
    out = capsys.readouterr().out.splitlines()
    assert [l.split(':')[0] for l in out] == ['tmux', 'split', 'extended-keys', 'config', 'ramabana-pane']
    assert '3.0a' in out[0] and '/bin/tmux' in out[0] and '3.1' in out[1] and str(tmp_path/'cfg'/'tmux.conf') in out[3]
    assert '/bin/ramabana-pane' in out[4] and box.asked == []
    s, box = mk(tmp_path, Box(have=set(), system='Linux'), environ={'TMUX': 'x'})
    s.doctor()
    out = capsys.readouterr().out.splitlines()
    assert 'not found' in out[0] and 'python -m ramabana.pane' in out[4]
    s, box = mk(tmp_path, Box(ext='off'), environ={'TMUX': 'x'})
    s.doctor()
    assert 'off' in capsys.readouterr().out.splitlines()[2] and not any('set' in c for c in box.calls)
