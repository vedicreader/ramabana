#!/usr/bin/env python
"""Time ramabana's startup in a pty: the tmux relaunch, the first prompt draw, and the model being ready.

    .venv/bin/python scripts/startup_time.py [--root nbs] [--profile full] [--runs 3]

`relaunch` is the outer process's time to exec tmux, through the console script `pyproject.toml` declares (a fake
tmux on PATH records it). The session numbers
come from the real `main` with `--tmux off`, hooked: `prompt` is the first paint, `prompt_tools` the moment
the system prompt and tools are built, `ready` when `Agent.start` returns, and `litesearch` whether it was
imported by then.

It starts the real default model, so a first run may download its weights, and it indexes `--root` (default `nbs/`)
in the background. Config goes to a temporary `--cfg`, so your sessions and history are untouched.
"""
import argparse, fcntl, json, os, pty, select, shutil, statistics, struct, subprocess, sys, tempfile, termios, time, tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = sys.executable
STRIP = ('TMUX', 'RAMABANA_TMUX', 'RAMABANA_WRAPPED', 'LEELA_TMUX', 'LEELA_WRAPPED')

PROBE = r'''
import json, os, sys, time
t0, dest, out = float(os.environ['T0']), os.environ['OUT'], {}
def mark(k, v=None):
    out.setdefault(k, round(time.time() - t0, 3) if v is None else v)
    open(dest, 'w').write(json.dumps(out))
import ramabana.cli as cli
from ramabana.agent import Agent
mark('import')
paint, start = cli.Ui.paint, Agent.start
def hooked_paint(self):
    mark('prompt'); return paint(self)
def hooked_start(self):
    self.system_prompt(); self.tools
    mark('prompt_tools'); mark('litesearch', 'litesearch' in sys.modules)
    b = start(self); mark('ready'); return b
cli.Ui.paint, Agent.start = hooked_paint, hooked_start
cli.main.__wrapped__(root=sys.argv[1], profile=sys.argv[2], cfg=sys.argv[3], tmux='off', pane='off')
'''

def env(**kw): return {k: v for k, v in os.environ.items() if k not in STRIP} | kw

def in_pty(argv, environ, done, timeout=60):
    "Run `argv` on a pty, draining it; once `done()` holds send ctrl+d. Returns the exit status."
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(argv[0], argv, environ)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
    end, sent = time.time() + timeout, False
    try:
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], .05)
            if r:
                try: got = os.read(fd, 65536)
                except OSError: break
                if b'\x1b[6n' in got: os.write(fd, b'\x1b[1;1R')   # the compositor asks where the cursor is
            if not sent and done():
                os.write(fd, b'\x04'); sent = True
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid: return status
        os.kill(pid, 9)
    finally: os.close(fd)
    return os.waitpid(pid, 0)[1]

def relaunch(tmp):
    "Seconds from spawning `ramabana` to its exec of tmux."
    bin_, mark = tmp/'bin', tmp/'exec'
    bin_.mkdir(exist_ok=True); mark.unlink(missing_ok=True)
    (bin_/'tmux').write_text(f"#!/bin/sh\n[ \"$1\" = -V ] && {{ echo 'tmux 3.5a'; exit 0; }}\n"
                             f"exec perl -MTime::HiRes=time -e 'open(F, \">{mark}\"); print F time'\n")
    (bin_/'tmux').chmod(0o755)
    subprocess.run([bin_/'tmux', '-V'], capture_output=True)   # macOS scans a new executable on its first run
    mod, fn = tomllib.loads((HERE/'pyproject.toml').read_text())['project']['scripts']['ramabana'].split(':')
    (exe := tmp/'ramabana').write_text(f'#!{PY}\nimport sys\nfrom {mod} import {fn}\nsys.exit({fn}())\n')   # the console script pip writes
    exe.chmod(0o755)
    t0 = time.time()
    in_pty([str(exe), '--cfg', str(tmp/'cfg')], env(PATH=f"{bin_}:{os.environ['PATH']}"), lambda: False, timeout=30)
    return round(float(mark.read_text()) - t0, 3)

def session(tmp, root, profile):
    "The hooked marks of one interactive start."
    out = tmp/'marks.json'; out.unlink(missing_ok=True)
    def done():
        try: m = json.loads(out.read_text())
        except (OSError, ValueError): return False
        return 'ready' in m and 'prompt' in m
    in_pty([PY, '-c', PROBE, root, profile, str(tmp/'cfg')], env(T0=repr(time.time()), OUT=str(out)), done)
    return json.loads(out.read_text())

def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--root', default=str(HERE/'nbs'))
    p.add_argument('--profile', default='auto')
    p.add_argument('--runs', type=int, default=3)
    a = p.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix='rama-startup-'))
    try:
        rows = [dict(relaunch=relaunch(tmp), **session(tmp, a.root, a.profile)) for _ in range(a.runs)]
    finally: shutil.rmtree(tmp, ignore_errors=True)
    for r in rows: print(json.dumps(r))
    keys = [k for k in rows[0] if isinstance(rows[0][k], float)]
    print('median', json.dumps({k: statistics.median(r[k] for r in rows if k in r) for k in keys}))

if __name__ == '__main__': main()
