"""The seam between the machine's beat and a session.

pobblebonk schedules an operating-system job, so it fires when nothing here is running. The two
halves meet in one SQLite database and never call each other: the beat leaves notes, a session
reads them under its own id. What is worth a plain test is that the reading never takes a turn
down, and that two sessions each see what the beat left rather than racing for it.
"""
import tempfile
import time

import pytest

from ramabana.agent import Agent
from ramabana.monitor import TICKS, beat_notes, on_tick, pob, pob_path, tick
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
