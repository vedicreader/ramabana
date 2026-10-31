"""The whole loop on a real tmux and a real pobblebonk beat: a folder moves, the beat reviews it, and a pane shows the review."""

import os, shutil, subprocess, tempfile, time

import pytest

from ramabana.monitor import pob
from ramabana.testing import fake_agent
from shalya.host import LocalHost

pytestmark = pytest.mark.slow
fastmux = pytest.importorskip('fastmux')
if shutil.which('tmux') is None: pytest.skip('tmux is not installed', allow_module_level=True)


def until(pred, timeout=8., every=.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (got := pred()): return got
        time.sleep(every)
    return pred()


def shown(pane):
    "The last 200 lines of `pane` as one line, each run of spaces and line breaks made one space, so a wrap between words does not matter."
    return ' '.join(subprocess.run(['tmux', 'capture-pane', '-p', '-J', '-S', '-200', '-t', pane], capture_output=True, text=True).stdout.split())


@pytest.fixture
def own_tmux(monkeypatch):
    "A private tmux server, so the test neither joins nor inherits the options of the tmux it runs in."
    d = tempfile.mkdtemp(prefix='rama-e2e-', dir='/tmp')  # a Unix socket path must stay short; tmp_path is too long
    monkeypatch.delenv('TMUX', raising=False)
    monkeypatch.setenv('TMUX_TMPDIR', d)
    yield d
    subprocess.run(['tmux', 'kill-server'], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def test_a_beat_reviews_a_folder_and_a_pane_shows_it(tmp_path, own_tmux):
    repo, cfg = tmp_path/'repo', tmp_path/'cfg'
    repo.mkdir(); (repo/'a.py').write_text('one\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    session = fastmux.new_session(cmd='cat', name=f'rama-e2e-{os.getpid()}', cwd=str(repo), width=240, height=60)
    try:
        host = LocalHost([str(repo)], tmux=fastmux.tmux(f'{session.name}:0.0'), index=False)
        a, be = fake_agent(host, cfg=cfg)
        a.monitors.add(str(repo), 'say what moved')
        p = pob(tmp_path/'pob.db')
        p.on('folders')(lambda fire: a.monitors.check(force=True) and 'checked')
        p.add('folders', every=1, start=time.time() - 5)
        (repo/'a.py').write_text('ONE\n')
        got = p.tick()
        assert [r['name'] for r in got.ran] == ['folders'] and got.ran[0]['status'] == 'ok'
        rec, = a.monitors.drain()
        assert rec['review'].split('\nstate:')[0] == 'sub answer'
        assert 'sub answer' in a.monitors.log.read_text()
        out = a.command('/watch monitors')
        assert out.startswith('watching monitors in pane'), out
        pid = out.rsplit(' ', 1)[-1]
        assert until(lambda: 'sub answer' in shown(pid)), shown(pid)
        out = a.command(f"/watch {rec['run_id']}")
        assert out.startswith('watching'), out
        rpid = out.rsplit(' ', 1)[-1]
        assert until(lambda: 'sub answer' in shown(rpid)), shown(rpid)
        assert 'finished' in a.command(f"/tell {rec['run_id']} anything")
        assert a.command('/unwatch').startswith('closed')
        a.close()
    finally:
        session.kill()
