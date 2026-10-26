from ramabana.monitor import pob
from ramabana.testing import fake_agent


def test_fake_agent_ignores_home_skills(tmp_path, monkeypatch):
    skill = tmp_path/'.agents'/'skills'/'zzz-home-only'
    skill.mkdir(parents=True)
    (skill/'SKILL.md').write_text('---\nname: zzz-home-only\ndescription: ZZZ_HOME_MARKER ' + 'x'*5000 + '\n---\n\nbody\n')
    monkeypatch.setenv('HOME', str(tmp_path))
    agent, _ = fake_agent()
    assert 'zzz-home-only' not in agent.system_prompt()
    assert 'zzz-home-only' not in {s.name for s in agent.skills}


def test_fake_agent_ignores_the_beat(tmp_path, monkeypatch):
    db = tmp_path/'pob.db'
    pob(db).note('nightly', 'ZZZ_BEAT_MARKER ' + 'x'*5000)
    monkeypatch.setattr('ramabana.agent.pob_path', lambda: db)
    agent, be = fake_agent(replies=['fine'])
    assert agent.beat_drain() == []
    assert agent.ask('hello') == 'fine'
    assert 'ZZZ_BEAT_MARKER' not in str(be.sent)