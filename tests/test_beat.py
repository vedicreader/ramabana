"""The seam between the machine's beat and a session.

pobblebonk schedules an operating-system job, so it fires when nothing here is running. The two
halves meet in one SQLite database and never call each other: the beat leaves notes, a session
reads them under its own id. What is worth a plain test is that the reading never takes a turn
down, and that two sessions each see what the beat left rather than racing for it.
"""
import tempfile
import time
from pathlib import Path

import pytest

from ramabana.agent import Agent
from ramabana.monitor import POB_READER, TICKS, beat_notes, beat_notice, on_tick, pob, tick
from ramabana.testing import MemHost

pobblebonk = pytest.importorskip('pobblebonk')


@pytest.fixture
def db(tmp_path): return str(tmp_path/'pob.db')


def test_a_machine_without_pobblebonk_reads_nothing_rather_than_failing(monkeypatch):
    "The absent branch, exercised on a machine that does have it, by hiding the import."
    import sys
    monkeypatch.setitem(sys.modules, 'pobblebonk.core', None)
    assert pob() is None
    assert beat_notes(pob()) == []
    assert beat_notice([]) == ''


def test_a_beat_that_cannot_be_read_never_reaches_the_turn(db):
    class _Locked:
        def drain(self, reader, limit=20): raise RuntimeError('database is locked')
    assert beat_notes(_Locked()) == []


def test_each_reader_sees_every_note_once(db):
    p = pob(db)
    p.note('watches', '2 of 5 fired')
    p.note('nightly', '')
    assert beat_notes(p) == ['watches: 2 of 5 fired', 'nightly']
    assert beat_notes(p) == [], 'the same note came back twice for one reader'
    # a second session is a second reader, and the offset is kept per reader
    assert beat_notes(p, reader='another') == ['watches: 2 of 5 fired', 'nightly']


def test_the_notice_is_empty_until_there_is_something_to_say(db):
    assert beat_notice([]) == ''
    got = beat_notice(['watches: 2 of 5 fired'])
    assert got.startswith('\n\n<beat>') and got.endswith('</beat>')
    assert '2 of 5 fired' in got


def test_one_beat_runs_a_schedule_and_leaves_what_it_found(db):
    @on_tick('t_beat')
    def _ran(fire): return 'the beat ran this'
    try:
        pob(db).add('t_beat', every='1s')
        time.sleep(1.2)
        assert tick.__wrapped__(db=db, quiet=True) == 0
        assert beat_notes(pob(db)) == ['t_beat: the beat ran this']
    finally: TICKS.pop('t_beat', None)


def test_a_schedule_nothing_registered_is_recorded_rather_than_silently_skipped(db):
    pob(db).add('t_orphan', every='1s')
    time.sleep(1.2)
    assert tick.__wrapped__(db=db, quiet=True) == 0
    left = beat_notes(pob(db))
    assert left and 'no callback registered' in left[0], left


def test_a_session_reads_the_beat_under_its_own_id_and_only_once(tmp_path, monkeypatch):
    import ramabana.monitor as mo
    # a real database at a real path, so `beat` opens it the way it would on a machine with a beat
    home = tmp_path/'.pobblebonk'
    home.mkdir()
    monkeypatch.setattr(mo, 'POB_HOME', home)
    pob(home/'pob.db').note('watches', '1 fired')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    assert a.beat_drain() == ['watches: 1 fired']
    assert a.beat_drain() == [], 'the same session read the note twice'

    b = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    assert b.beat_drain() == ['watches: 1 fired'], 'a second session missed what the beat left'
    assert b.beat_drain() == []


def test_a_session_with_no_beat_on_the_machine_reads_nothing(tmp_path, monkeypatch):
    import ramabana.monitor as mo
    monkeypatch.setattr(mo, 'POB_HOME', tmp_path/'nowhere')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    assert a.beat is None
    assert a.beat_drain() == []


def test_a_session_reads_under_a_name_that_carries_this_package_and_its_own_id(tmp_path, monkeypatch):
    "Two packages sharing one database must not consume each other's notes."
    import ramabana.monitor as mo
    home = tmp_path/'.pobblebonk'
    home.mkdir()
    monkeypatch.setattr(mo, 'POB_HOME', home)
    pob(home/'pob.db').note('watches', 'x')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    a.beat_drain()
    assert a._beat_reader.startswith(f'{POB_READER}:')
    assert a.session_id in a._beat_reader


def test_the_reader_does_not_move_when_a_session_is_resumed(tmp_path, monkeypatch):
    "`resume_session` renames the session. A reader that followed it would replay what was carried."
    import ramabana.monitor as mo
    home = tmp_path/'.pobblebonk'
    home.mkdir()
    monkeypatch.setattr(mo, 'POB_HOME', home)
    pob(home/'pob.db').note('watches', 'x')
    a = Agent(host=MemHost({'/p/x.py': 'x=1'}), extensions=False)
    assert a.beat_drain() == ['watches: x']
    was = a._beat_reader
    a.session_id = 'some-other-session'
    assert a._beat_reader == was
    assert a.beat_drain() == [], 'the note came back after the session was renamed'


def test_the_entry_point_says_what_is_missing_rather_than_dying_silently(monkeypatch, capsys):
    "What a cron job with a bare environment gets: a reason on stderr and a non-zero exit."
    import sys
    monkeypatch.setitem(sys.modules, 'pobblebonk.core', None)
    assert tick.__wrapped__(db='', quiet=True) == 1
    assert "pobblebonk is not installed" in capsys.readouterr().err
