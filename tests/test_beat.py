"""The seam between the machine's beat and a session.

pobblebonk schedules an operating-system job, so it fires when nothing here is running. The two
halves meet in one SQLite database and never call each other: the beat leaves notes, a session
reads them under its own id. What is worth a plain test is that the reading never takes a turn
down, and that two sessions each see what the beat left rather than racing for it.
"""
import subprocess
import sys
import tempfile
import time

import pytest

from ramabana.agent import Agent
from ramabana.monitor import TICKS, beat_command, beat_notes, on_tick, pob, pob_path, tick
from ramabana.testing import MemHost

pobblebonk = pytest.importorskip('pobblebonk')


@pytest.fixture
def db(tmp_path): return str(tmp_path/'pob.db')


def test_each_reader_sees_every_note_once(db):
    p = pob(db)
    p.note('watches', '2 of 5 fired')
    p.note('nightly', '')
    assert beat_notes(p) == ['watches: 2 of 5 fired', 'nightly']
    assert beat_notes(p) == [], 'the same note came back twice for one reader'
    # a second session is a second reader, and the offset is kept per reader
    assert beat_notes(p, reader='another') == ['watches: 2 of 5 fired', 'nightly']


def test_one_beat_runs_a_schedule_and_leaves_what_it_found(db):
    @on_tick('t_beat')
    def _ran(fire): return 'the beat ran this'
    try:
        pob(db).add('t_beat', every='1s')
        time.sleep(1.2)
        assert tick.__wrapped__(db=db, quiet=True) == 0
        assert beat_notes(pob(db)) == ['t_beat: the beat ran this']
    finally: TICKS.pop('t_beat', None)


def test_an_installed_package_names_its_tick_through_an_entry_point(db, tmp_path, monkeypatch):
    site = tmp_path/'site'
    info = site/'t_pkg_tick-0.dist-info'
    info.mkdir(parents=True)
    (info/'METADATA').write_text('Name: t-pkg-tick\nVersion: 0\n')
    (info/'entry_points.txt').write_text('[ramabana.ticks]\nt_pkg = t_pkg_tick:run\n')
    (site/'t_pkg_tick.py').write_text("def run(fire): return f'a package ran {fire.schedule}'\n")
    monkeypatch.syspath_prepend(str(site))
    try:
        assert tick.__wrapped__(db=db, quiet=True) == 0
        assert 't_pkg_tick' not in sys.modules, 'a beat imported a package whose schedule did not fire'
        pob(db).add('t_pkg', every='1s')
        time.sleep(1.2)
        assert tick.__wrapped__(db=db, quiet=True) == 0
        assert beat_notes(pob(db)) == ['t_pkg: a package ran t_pkg']
    finally: sys.modules.pop('t_pkg_tick', None)


@pytest.mark.skipif(sys.platform == 'win32', reason='the launcher here is a shell script')
def test_the_installed_launcher_runs_a_tick_whose_path_has_a_space(tmp_path):
    "uv installs tools under `~/Library/Application Support` on macOS."
    from pobblebonk.heartbeat import launcher
    exe = tmp_path/'Application Support'/'ramabana-tick'
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\necho ran "$@"\n'); exe.chmod(0o755)
    subprocess.run([str(launcher(beat_command(exe), dirn=tmp_path, tag='t', win=False))], check=True)
    assert (tmp_path/'t.log').read_text() == 'ran --quiet\n'


@pytest.mark.skipif(sys.platform == 'win32', reason='the launcher here is a shell script')
def test_the_installed_launcher_carries_the_installing_path(tmp_path, monkeypatch):
    "launchd and cron run a job on `/usr/bin:/bin`, where Dhrona's nightly found neither `claude` nor `git-lfs`."
    from pobblebonk.heartbeat import launcher
    tools = tmp_path/"it's $HOME tools"/'bin'
    tools.mkdir(parents=True)
    (tools/'claude').write_text('#!/bin/sh\n'); (tools/'claude').chmod(0o755)
    exe = tmp_path/'ramabana-tick'
    exe.write_text('#!/bin/sh\ncommand -v claude || echo missing\n'); exe.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tools}:/usr/bin:/bin')
    sh = launcher(beat_command(exe), dirn=tmp_path, tag='t', win=False)
    subprocess.run([str(sh)], check=True, env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(tmp_path)})
    assert (tmp_path/'t.log').read_text() == f'{tools}/claude\n'


def test_a_beat_installed_without_a_path_runs_the_bare_command(monkeypatch):
    monkeypatch.delenv('PATH', raising=False)
    assert beat_command('/x/ramabana-tick') == '/x/ramabana-tick --quiet'
    assert beat_command('/x/ramabana-tick', path='') == '/x/ramabana-tick --quiet'


def test_the_windows_beat_command_is_unchanged(monkeypatch):
    "Task Scheduler gives a job the user's environment."
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert beat_command(r'C:\a b\ramabana-tick', path='C:\\bin') == r'"C:\a b\ramabana-tick" --quiet'


def test_a_session_reads_the_beat_under_its_own_id_and_only_once(tmp_path, monkeypatch):
    import ramabana.monitor as mo
    # a real database at a real path, so `beat` opens it the way it would on a machine with a beat
    home = tmp_path/'.pobblebonk'
    home.mkdir()
    monkeypatch.setattr(mo, 'POB_HOME', home)
    pob(home/'pob.db').note('watches', '1 fired')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False, profile='full')
    assert a.beat_drain() == ['watches: 1 fired']
    assert a.beat_drain() == [], 'the same session read the note twice'

    b = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False, profile='full')
    assert b.beat_drain() == ['watches: 1 fired'], 'a second session missed what the beat left'
    assert b.beat_drain() == []


def test_the_reader_does_not_move_when_a_session_is_resumed(tmp_path, monkeypatch):
    "`resume_session` renames the session. A reader that followed it would replay what was carried."
    import ramabana.monitor as mo
    home = tmp_path/'.pobblebonk'
    home.mkdir()
    monkeypatch.setattr(mo, 'POB_HOME', home)
    pob(home/'pob.db').note('watches', 'x')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False, profile='full')
    assert a.beat_drain() == ['watches: x']
    was = a._beat_reader
    a.session_id = 'some-other-session'
    assert a._beat_reader == was
    assert a.beat_drain() == [], 'the note came back after the session was renamed'
