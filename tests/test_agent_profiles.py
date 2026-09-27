"""Named `/agent` profiles: markdown files a delegation can be briefed and routed with."""
from ramabana.testing import FakeBackend, MemHost, SPEC, fake_agent
from ramabana.tools import named_agent, subagent_tools


def test_agent_profiles_are_discovered_from_project_then_cfg_and_project_wins(tmp_path):
    a, _ = fake_agent(host=MemHost(root=str(tmp_path)), cfg=tmp_path)
    assert a.agents == {}
    assert a.command('/agent') == 'no agent profiles found (.agents/agents/ or <cfg>/agents/)'

    (tmp_path/'agents').mkdir()
    (tmp_path/'agents'/'reviewer.md').write_text('---\ndescription: reviews diffs\n---\nBe a strict reviewer.\n')
    a.reload()
    assert a.agents['reviewer']['body'] == 'Be a strict reviewer.'
    assert 'reviewer' in a.command('/agent') and 'reviews diffs' in a.command('/agent')
    assert a.command('/agent reviewer') == 'reviewer\n\nBe a strict reviewer.'
    assert 'no agent profile' in a.command('/agent nosuch')

    project = tmp_path/'.agents'/'agents'
    project.mkdir(parents=True)
    (project/'reviewer.md').write_text('---\ndescription: the project one wins\nmodel: gpt-4.1\n---\nProject reviewer body.\n')
    a.reload()
    assert a.agents['reviewer']['body'] == 'Project reviewer body.'
    assert a.agents['reviewer']['model'] == 'gpt-4.1'
    assert 'agent' in a.commands()


def test_named_agent_reports_a_missing_profile_by_name():
    assert named_agent(None, 'x') == (None, '')
    assert named_agent(lambda: {}, '') == (None, '')
    prof, note = named_agent(lambda: {'reviewer': {'body': 'x'}}, 'nosuch')
    assert prof is None and 'reviewer' in note and 'nosuch' in note


def test_delegate_search_briefs_and_routes_with_a_named_agent_profile():
    be, cloud = FakeBackend(SPEC), FakeBackend(SPEC)
    profiles = {'reviewer': {'description': '', 'model': 'gpt-4.1', 'body': 'Be a strict reviewer.'}}
    routed = []
    def get_cloud_backend(model):
        routed.append(model)
        return cloud
    tools = subagent_tools(lambda: be, lambda: [], get_cloud_backend=get_cloud_backend,
                           get_agents=lambda: profiles)
    delegate_search = next(t for t in tools if t.__name__ == 'delegate_search')

    delegate_search(question='what is here?')
    assert be.spawned and not cloud.spawned, 'a plain call never reaches the cloud backend'
    assert not be.spawned[-1].sp.strip().startswith('Be a strict')

    delegate_search(question='review this', agent='reviewer')
    assert routed == ['gpt-4.1'] and cloud.spawned, 'a named profile with a model routes to it'
    assert 'Be a strict reviewer.' in cloud.spawned[-1].sp

    missing = delegate_search(question='x', agent='nosuch')
    assert 'no agent profile named nosuch' in missing
