from inspect import signature
from ramabana.cli import main
from ramabana.core import Routing, JOBS, DFLT_LOCAL, resolve
from ramabana.testing import fake_agent


def test_default_routes_and_subagent_settings(monkeypatch):
    for prefix in ('RAMABANA_', 'LEELA_'):
        for key in ('MODEL', *(f'MODEL_{job.upper()}' for job in JOBS)):
            monkeypatch.delenv(prefix + key, raising=False)
    routing = Routing()
    expected = dict(turn='claude-opus-5-5', subagent='claude-sonnet-5-5',
                    oneshot='gpt-6.1-luna', inline='gpt-6.1-luna', summary='gpt-6.1-luna',
                    classify='claude-haiku-5-5', completion='claude-haiku-5-5')
    assert {job: routing.name_for(job) for job in JOBS} == expected
    assert resolve('gpt-6.1-luna').model_id == 'openai/gpt-6.1-luna'
    assert not DFLT_LOCAL.startswith('gemma')
    assert signature(main).parameters['subagent_writes'].default is True
    agent, _ = fake_agent()
    assert agent.subagents and agent.subagent_writes
    assert (agent.subagent_steps, agent.subagent_timeout, agent.subagent_depth) == (60, 1800, 2)
