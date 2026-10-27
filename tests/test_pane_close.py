"A finished run's transcript pane closes by itself, and clicks on the board reuse one pane."

import json, time

from test_pane import _board, _click, _viewer


class FakeTmux:
    "A tmux server for the viewer: the panes it holds and what each runs, every command it was given, and every pane it killed."
    def __init__(self, *others):
        self.panes, self.calls, self.killed, self.n = {p: 'someone else' for p in others}, [], [], 10

    def __call__(self, *a):
        self.calls.append(a)
        target = a[a.index('-t') + 1] if '-t' in a else None
        if a[0] == 'split-window': self.n += 1; self.panes[f'%{self.n}'] = a[-1]; return f'%{self.n}'
        if a[0] == 'respawn-pane': self.panes[target] = a[-1]
        if a[0] == 'kill-pane': self.killed.append(target); self.panes.pop(target, None)
        if a[0] == 'list-panes': return '\n'.join(self.panes)
        return ''

    def transcripts(self): return {p: c for p, c in self.panes.items() if c != 'someone else'}
    def ran(self, cmd): return [c for c in self.calls if c[0] == cmd]


def _watching(tmp_path, *others, **extra):
    "A viewer over a board whose chat pane is `%7`, with a `FakeTmux` that also holds the panes of `others`."
    now, tmux = time.time(), FakeTmux('%7', *others)
    snap = {**_board(now), 'target': 'main', 'chat_pane': '%7', **extra}
    for s in snap['subs']: s['log'] = str(tmp_path/f"{s['id']}.log")
    v, p = _viewer(tmp_path, snap)
    v.tmux = tmux
    return v, p, tmux, snap


def _rewrite(v, p, snap):
    p.write_text(json.dumps(snap))
    v.reload()


def test_a_finished_runs_pane_closes_after_the_linger_and_a_running_ones_stays(tmp_path):
    "The board's pane for a run is killed `PANE_LINGER` seconds after the run ends, never while it runs."
    from ramabana.pane import PANE_LINGER
    v, p, tmux, snap = _watching(tmp_path)
    _click(v, ('sub', 'run_aaa'))
    (pid,) = tmux.transcripts()
    v.reap(1000.0); v.reap(1000.0 + 10 * PANE_LINGER)
    assert tmux.killed == [], 'a running sub-agent keeps its pane'
    snap['subs'][0]['state'] = 'completed'
    _rewrite(v, p, snap)
    v.reap(2000.0)
    assert tmux.killed == [], 'the final answer is still being written'
    v.reap(2000.0 + PANE_LINGER - 0.5)
    assert tmux.killed == []
    v.reap(2000.0 + PANE_LINGER + 0.1)
    assert tmux.killed == [pid] and tmux.transcripts() == {}


def test_only_the_pane_the_viewer_opened_is_ever_killed(tmp_path):
    "The chat pane in the snapshot and every other pane in the session survive, and a pane the user closed is not killed again."
    v, p, tmux, snap = _watching(tmp_path, '%99')
    _click(v, ('sub', 'run_aaa'))
    (pid,) = tmux.transcripts()
    snap['subs'] = []
    _rewrite(v, p, snap)
    v.reap(10.0); v.reap(1000.0)
    assert tmux.killed == [pid] and set(tmux.panes) == {'%7', '%99'}
    (again := tmp_path/'again').mkdir()
    v2, p2, tmux2, snap2 = _watching(again)
    _click(v2, ('sub', 'run_aaa'))
    tmux2.panes.pop(next(iter(tmux2.transcripts())))
    snap2['subs'][0]['state'] = 'failed'
    _rewrite(v2, p2, snap2)
    v2.reap(10.0); v2.reap(1000.0)
    assert tmux2.killed == [], 'tmux no longer has the pane, so there is nothing to kill'


def test_with_pane_close_done_off_nothing_is_killed(tmp_path):
    v, p, tmux, snap = _watching(tmp_path, close_done=False)
    _click(v, ('sub', 'run_aaa'))
    snap['subs'][0]['state'] = 'completed'
    _rewrite(v, p, snap)
    v.reap(10.0); v.reap(1000.0)
    assert tmux.killed == [] and len(tmux.transcripts()) == 1


def test_clicks_reuse_one_transcript_pane_and_main_closes_it(tmp_path):
    "Two clicks on two runs leave one pane showing the second; a pane the user killed is recreated; `main` closes it."
    v, p, tmux, snap = _watching(tmp_path)
    snap['subs'][1]['state'] = 'running'
    _rewrite(v, p, snap)
    _click(v, ('sub', 'run_aaa'))
    _click(v, ('sub', 'run_bbb'))
    (pid, cmd), = tmux.transcripts().items()
    assert 'run_bbb.log' in cmd and len(tmux.ran('split-window')) == 1 and len(tmux.ran('respawn-pane')) == 1
    _click(v, ('sub', 'run_bbb'))
    assert tmux.transcripts() == {pid: cmd}, 'a click on the run it already shows changes nothing'
    tmux.panes.pop(pid)
    _click(v, ('sub', 'run_aaa'))
    (pid2, cmd2), = tmux.transcripts().items()
    assert pid2 != pid and 'run_aaa.log' in cmd2, 'the pane the user killed is made again'
    _click(v, ('main', 'main'))
    assert tmux.transcripts() == {} and tmux.killed == [pid2]


def test_a_click_on_a_finished_or_absent_run_opens_no_pane(tmp_path):
    v, p, tmux, snap = _watching(tmp_path)
    _click(v, ('sub', 'run_bbb'))
    v.talk(('sub', 'run_zzz'))
    assert tmux.ran('split-window') == [] and tmux.transcripts() == {}


def test_the_pane_closes_when_its_run_leaves_the_list(tmp_path):
    from ramabana.pane import PANE_LINGER
    v, p, tmux, snap = _watching(tmp_path)
    _click(v, ('sub', 'run_aaa'))
    snap['subs'] = [s for s in snap['subs'] if s['id'] != 'run_aaa']
    _rewrite(v, p, snap)
    v.reap(500.0)
    assert len(tmux.transcripts()) == 1
    v.reap(500.0 + PANE_LINGER + 0.1)
    assert tmux.transcripts() == {}
