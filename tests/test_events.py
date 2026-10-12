"A host page in another process tails one job: `events_to` writes one JSON line per thing that happened."
import json

from ramabana import agent
from ramabana.testing import fake_agent


def _lines(p): return [json.loads(l) for l in p.read_text().splitlines()]

def test_every_kind_of_event_is_one_json_line_and_the_file_rotates(tmp_path):
    a, _ = fake_agent(cfg=tmp_path/'cfg', approvals=agent.Approvals(tools={'edit_file'}, timeout=5))
    log = a.events_to(tmp_path/'job.events')
    a.ask('hello')
    act = a.activity.start('view_file', {'path': 'a.py'}); a.activity.finish(act, 'text')
    a.approvals.listen(on_ask=lambda x: a.approvals.answer(x.id, True))
    a.approvals.request('edit_file', {'path': 'a.py'})
    a.command('/todo check the sources')
    a._heard_steer(['also read the notes'])
    rows = _lines(log)
    kinds = [r['kind'] for r in rows]
    for k in ('turn_start', 'turn_end', 'act', 'ask', 'plan', 'steer'): assert k in kinds, (k, kinds)
    assert all(r['session'] == a.session_id and r['at'] for r in rows)
    end = next(r for r in rows if r['kind'] == 'turn_end')
    assert end['state'] == 'complete' and 'usage' in end and end['turn_id']
    asks = [r for r in rows if r['kind'] == 'ask']
    assert [r['event'] for r in asks] == ['raised', 'answered'] and asks[1]['answer'] is True
    assert next(r for r in rows if r['kind'] == 'steer')['messages'] == ['also read the notes']
    assert any(r['kind'] == 'act' and r['act']['tool'] == 'view_file' and r['act']['done'] for r in rows), 'a call is reported with its fields'
    small = a.events_to(tmp_path/'small.events', max_bytes=400)
    for _ in range(6): a._heard_steer(['x' * 100])
    assert small.with_name('small.events.1').exists() and small.stat().st_size <= 400, 'a full file rolls over to .1'


def test_an_embedding_host_can_keep_python_skills_and_rules_to_itself(tmp_path, monkeypatch):
    "Defaults made for a person at a terminal: Python in this process, the user's home skills, one rules file per config."
    from ramabana.agent import mk_agent
    home = tmp_path/'home'
    (home/'.agents'/'skills'/'stray').mkdir(parents=True)
    (home/'.agents'/'skills'/'stray'/'SKILL.md').write_text('---\nname: stray\ndescription: from the user home\n---\nbody\n')
    monkeypatch.setenv('HOME', str(home))
    rules = tmp_path/'job-rules.json'
    kw = dict(web=False, extensions=False, subagents=False)
    a, _ = mk_agent([str(tmp_path)], python='off', global_skills=False, rules_path=rules, extra_sp='Work only on the Isha Upanishad.', cfg=tmp_path/'cfg', **kw)
    names = {t.__name__ for t in a.tools}
    assert not names & {'run_python', 'inspect_python', 'restart_kernel', 'read_terminal'}, names
    assert 'stray' not in {s.name for s in a.skills} and a.approvals.rules_path == rules
    sp = a.system_prompt()
    assert sp.index('Work only on the Isha Upanishad.') > sp.index('You are Ramabana'), 'added to the briefing, not in place of it'
    b, _ = mk_agent([str(tmp_path)], cfg=tmp_path/'cfg2', **kw)
    assert 'run_python' in {t.__name__ for t in b.tools} and 'stray' in {s.name for s in b.skills}, 'the defaults are unchanged'
    a.close(); b.close()
