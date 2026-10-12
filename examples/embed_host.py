"""One agent job, run the way a long-running host such as a web app runs it.

The job gets a folder to write and a reference folder to read, a policy that lets read-only shell commands
through, a page that answers approvals by id, an event file to tail, a budget, and a typed result.

Run it by hand on a real model:

    python examples/embed_host.py --model claude/claude-haiku-5-5

`tests/test_embed_example.py` runs `run_job` against a scripted backend in CI.
"""
import argparse, json, shlex, tempfile, threading
from pathlib import Path

from pydantic import BaseModel

from ramabana.agent import mk_agent


class Found(BaseModel):
    function: str   # the function's name
    file: str       # the file that defines it


READERS = {'rg', 'ls', 'cat'}
SHELL_SYNTAX = set(';&|<>`$(){}\n')

def reads_only(name, args):
    "A host policy: a lone `rg`, `ls` or `cat` runs unasked; anything that chains, redirects or substitutes is put to a person."
    if name != 'run_shell': return None
    cmd = str(args.get('command', ''))
    try: words = [] if SHELL_SYNTAX & set(cmd) else shlex.split(cmd)
    except ValueError: return 'ask'
    if not words or words[0] not in READERS or any(w.startswith('--pre') for w in words): return 'ask'   # `rg --pre` runs a program
    return 'allow'


def page(approvals, answered):
    "A stand-in for the web page: it answers each ask by id, from its own thread, and notes what it answered."
    def on_ask(ask):
        answered.append(ask.id)
        threading.Timer(0.2, approvals.answer, (ask.id, True)).start()
    return approvals.listen(on_ask=on_ask)


def run_job(work, ref, cfg, model=None, max_cost=0.50):
    "Find the function in `ref`, write its name into `work`, and hand it back typed. Returns the `TurnResult`, the event file and the asks answered."
    a, host = mk_agent([str(work)], read_roots=[str(ref)], model=model, approve='ask', cfg=cfg,
                       python='off', global_skills=False, rules_path=cfg/'job-rules.json',
                       no_listener='wait', timeout=600, max_cost=max_cost, web=False, extensions=False, subagents=False)
    a.approvals.policy = reads_only
    events, answered = a.events_to(cfg/'job.events'), []
    stop = page(a.approvals, answered)
    try:
        r = a.ask(f'In the read-only folder {ref}, find the Python function defined in source.py. '
                  f'Then create the file {work}/notes.txt containing just that function name.', schema=Found, result=True)
    finally:
        stop()
        a.close()
    return r, events, answered


def make_folders(base):
    "A writable folder, a reference folder holding `source.py`, and a config folder, under `base`."
    work, ref, cfg = base/'work', base/'ref', base/'cfg'
    for d in (work, ref, cfg): d.mkdir(parents=True, exist_ok=True)
    (ref/'source.py').write_text('def lawful_source(url):\n    "Whether a source may be used."\n    return url.startswith("https://")\n')
    return work, ref, cfg


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--model', default='claude/claude-haiku-5-5')
    args = p.parse_args()
    work, ref, cfg = make_folders(Path(tempfile.mkdtemp()))
    r, events, answered = run_job(work, ref, cfg, model=args.model)
    kinds = [json.loads(l)['kind'] for l in events.read_text().splitlines()]
    print(f'state {r.state} · result {r.result} · ${r.usage.get("cost", 0):.4f}')
    print(f'notes.txt: {(work/"notes.txt").read_text() if (work/"notes.txt").exists() else "(not written)"}')
    print(f'asks answered: {len(answered)} · events: {len(kinds)} ({", ".join(sorted(set(kinds)))})')
