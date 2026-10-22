"`/watch RUN` panes close when the run is done, and only the panes `/watch` opened."

from types import SimpleNamespace as NS

from ramabana.setup import PANE_LINGER
from ramabana.testing import fake_agent


def _watching(tmp_path):
    "An agent whose host opens and closes recorded panes, with one running run `run_a`."
    a, _ = fake_agent(cfg=tmp_path/'cfg')
    opened, closed, runs = {}, [], {'run_a': NS(log=tmp_path/'run_a.log', terminal=False)}
    a.run = lambda rid=None: runs.get(rid)
    a.host.open_pane = lambda cmd, title='': opened.setdefault(title, f'%{len(opened) + 20}')
    a.host.close_pane = closed.append
    return a, runs, opened, closed


def test_a_watched_runs_pane_closes_after_the_linger_and_a_running_ones_stays(tmp_path):
    a, runs, opened, closed = _watching(tmp_path)
    assert a.watch('run_a').startswith('watching run_a in pane')
    assert a.reap_panes(100.0) == [] and a.reap_panes(100.0 + 10 * PANE_LINGER) == [] and closed == []
    runs['run_a'].terminal = True
    assert a.reap_panes(200.0) == [] and a.reap_panes(200.0 + PANE_LINGER - 0.5) == []
    assert a.reap_panes(200.0 + PANE_LINGER + 0.1) == ['run_a'] and closed == [opened['run_a']]
    assert a.unwatch().startswith('nothing was being watched')


def test_the_monitors_pane_and_panes_watch_did_not_open_are_never_closed(tmp_path):
    a, runs, opened, closed = _watching(tmp_path)
    a.watch('monitors'); a.watch('run_a')
    a.host.open_pane('someone else')   # the user's own pane, which `/watch` never recorded
    runs['run_a'].terminal = True
    a.reap_panes(1.0); a.reap_panes(1000.0)
    assert 'monitors' in opened and closed == [opened['run_a']] and 'monitors' in a._panes


def test_with_pane_close_done_off_no_watch_pane_is_closed(tmp_path, monkeypatch):
    import ramabana.agent as agent
    monkeypatch.setattr(agent, 'setting', lambda k, d=None: False if k == 'pane_close_done' else d)
    a, runs, opened, closed = _watching(tmp_path)
    a.watch('run_a')
    runs['run_a'].terminal = True
    a.reap_panes(1.0); a.reap_panes(1000.0)
    assert closed == []


def test_a_pane_asked_for_after_the_run_ended_stays_until_unwatch(tmp_path):
    a, runs, opened, closed = _watching(tmp_path)
    runs['run_a'].terminal = True
    a.watch('run_a')
    a.reap_panes(1.0); a.reap_panes(1000.0)
    assert closed == [] and a.unwatch('run_a') == 'closed run_a' and closed == [opened['run_a']]