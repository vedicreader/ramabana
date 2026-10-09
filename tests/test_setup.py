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
        if 'install' in cmd and isinstance(self.code, BaseException): raise self.code
        if 'install' in cmd and self.code == 0: self.have.add('tmux')
        return SimpleNamespace(returncode=self.code if 'install' in cmd else 0, stdout='')
    def ask(self, q):
        self.asked.append(q)
        if isinstance(self.answer, BaseException): raise self.answer
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
    for line in ('escape-time 10', 'mouse on', 'status off', 'remain-on-exit off', 'destroy-unattached on', 'default-terminal', 'RGB'):
        assert line in old
    s, box = mk(tmp_path)
    p = s.conf()
    assert p == tmp_path/'cfg'/'tmux.conf' and p.read_text() == new
    p.touch()
    import os
    os.utime(p, (0, 0))
    s.conf()
    assert p.stat().st_mtime == 0
    s, box = mk(tmp_path, Box(version='tmux 3.4'))
    assert s.conf().read_text() == mid and p.stat().st_mtime > 0

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

@pytest.mark.parametrize('code', [1, KeyboardInterrupt()])
def test_a_failed_or_interrupted_install_saves_nothing_and_continues_without_tmux(tmp_path, capsys, code):
    s, box = mk(tmp_path, Box(have={'brew'}, answer='y', code=code))
    s.launch()
    assert ['brew', 'install', 'tmux'] in box.calls and box.execd is None and '--doctor' in capsys.readouterr().err
    assert not (tmp_path/'cfg'/'setup.json').exists()
    s2, box2 = mk(tmp_path, Box(have={'brew'}, answer='y'))
    s2.launch()
    assert len(box2.asked) == 1 and box2.execd is not None and s2._seen() == {'install_tmux': 'yes'}
