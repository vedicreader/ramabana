from pathlib import Path
import importlib.util
from runpy import run_path
from types import SimpleNamespace

import pytest
from shalya.skills import Registry, check

MOD = Path(__file__).parents[1] / 'examples/mods/gate'


class FakeAsk:
    def __init__(self, answer): self.answer = answer
    def reply(self): return None if self.answer else 'refused: not ready'


class FakeAgent:
    def __init__(self, root, answer=True):
        self.host = SimpleNamespace(roots=[str(root)])
        self.answer, self.asks = answer, []

    def ask_user(self, title, preview):
        self.asks.append((title, preview))
        return FakeAsk(self.answer)


@pytest.fixture
def gate():
    reg = Registry()
    run_path(str(MOD / 'mod.py'))['setup'](reg)
    return reg


def tool(reg, agent, name, args):
    return reg.fire('before_tool', agent, name, args)[0]


def turn(reg, agent, prompt):
    return reg.fire('before_turn', agent, prompt)[0]


def command(reg, agent, arg=''):
    return reg.commands['gate'][0](agent, arg)


def test_registration():
    result = check(MOD)
    assert result['mods'][0]['on'], result['mods'][0]['note']
    assert result['hooks'] == {'before_tool': 1, 'before_turn': 1}
    assert result['commands'] == ['gate']
    assert len(result['status']) == 1


@pytest.mark.parametrize('cmd', [
    'rm -rf thing', 'rm -r thing', 'rm -f -r thing', 'rm --force --recursive thing', 'git push --force', 'git push -f',
    'git reset --hard', 'git clean -fd', 'git clean -df', 'git clean -f -d', 'chmod -R 777 thing', 'dd if=input of=output',
    'mkfs /dev/test', 'cat x > /dev/test', 'sudo anything',
])
def test_risky_shell(gate, tmp_path, cmd):
    agent = FakeAgent(tmp_path)
    assert tool(gate, agent, 'run_shell', {'command': cmd}) is None
    assert len(agent.asks) == 1
    assert cmd in agent.asks[0][1]
    agent.answer = False
    assert tool(gate, agent, 'run_shell', {'command': cmd}) == 'gate: refused: not ready'


def test_tools_and_preview(gate, tmp_path):
    agent = FakeAgent(tmp_path)
    folder = tmp_path / 'folder with spaces'
    folder.mkdir()
    (folder / 'one').write_text('1')
    (folder / 'nested').mkdir()
    (folder / 'nested' / 'two').write_text('2')
    assert tool(gate, agent, 'run_shell', {'command': "rm -rf 'folder with spaces'", 'cwd': str(tmp_path)}) is None
    assert 'folder with spaces' in agent.asks[-1][1]
    assert '2 files' in agent.asks[-1][1]
    assert tool(gate, agent, 'run_shell', {'command': 'rm -r nested', 'cwd': 'folder with spaces'}) is None
    assert '1 files' in agent.asks[-1][1]
    for name, args in [('git_remote', {'op': 'push'}), ('git_commit', {'message': 'message'})]:
        assert tool(gate, agent, name, args) is None
        assert 'git ' in agent.asks[-1][1] and 'branch' in agent.asks[-1][1].lower()
    count = len(agent.asks)
    for cmd in ('ls', 'git status', 'rm missing', 'rm -f missing', 'git push', 'git reset --soft'):
        assert tool(gate, agent, 'run_shell', {'command': cmd}) is None
    assert tool(gate, agent, 'git_remote', {'op': 'fetch'}) is None
    assert len(agent.asks) == count
    (tmp_path / 'link').symlink_to(folder, target_is_directory=True)
    tool(gate, agent, 'run_shell', {'command': 'rm -r link'})
    assert 'file count unavailable' in agent.asks[-1][1]
    tool(gate, agent, 'run_shell', {'command': 'rm -r ../outside'})
    assert 'file count unavailable' in agent.asks[-1][1]
    (tmp_path / '-target').write_text('x')
    tool(gate, agent, 'run_shell', {'command': 'rm -r -- -target'})
    assert '-target: 1 files' in agent.asks[-1][1]
    assert tool(gate, agent, 'run_shell', {'command': 'rm -r x', 'cwd': object()}).startswith('gate: ')
    assert tool(gate, agent, 'run_shell', {'command': None}).startswith('gate: ')


def test_failing_hook_is_refused(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('gate_mod', MOD / 'mod.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    reg = Registry()
    reg.add_mod('gate', mod.setup)
    assert reg.mods[0].on, reg.mods[0].note
    agent = FakeAgent(tmp_path)

    def boom(*args, **kwargs): raise RuntimeError('boom')
    monkeypatch.setattr(mod, 'decision', boom)
    assert tool(reg, agent, 'git_commit', {}) == 'gate: could not evaluate action'
    assert turn(reg, agent, 'release') == 'gate: could not evaluate turn'

    # the hook catches every Exception, so a failure it cannot handle is one its handler no longer matches
    monkeypatch.setattr(mod, 'Exception', type('Unhandled', (BaseException,), {}), raising=False)
    assert tool(reg, agent, 'git_commit', {}).startswith('mod gate failed: ')
    assert turn(reg, agent, 'release') == 'mod gate failed: boom'
    assert tool(reg, agent, 'run_shell', {'command': 'ls'}) is None


def test_real_git_branch(gate):
    root = MOD.parents[2]
    host = SimpleNamespace(roots=[str(root)], check=lambda path, **kwargs: Path(path))
    agent = FakeAgent(root)
    agent.host = host
    assert tool(gate, agent, 'git_remote', {'op': 'push'}) is None
    assert 'branch: unknown' not in agent.asks[-1][1]


def test_turn_commands_and_old_agent(gate, tmp_path):
    agent = FakeAgent(tmp_path, False)
    assert turn(gate, agent, 'RELEASE then publish and deploy') == 'gate: release checklist not confirmed'
    assert len(agent.asks) == 1
    assert all(s in agent.asks[0][1] for s in ('CHANGELOG', 'Version', 'Tests'))
    assert turn(gate, agent, 'prerelease') is None
    assert command(gate, agent).startswith('gate on;')
    assert gate.status_segments[0](agent) == 'gate'
    command(gate, agent, 'off')
    assert gate.status_segments[0](agent) is None
    assert turn(gate, agent, 'deploy') is None
    assert tool(gate, agent, 'run_shell', {'command': 'rm -rf x'}) is None
    assert len(agent.asks) == 1
    command(gate, agent, 'on')
    assert 'invalid' in command(gate, agent, 'add [').lower()
    command(gate, agent, r'add \bterraform\s+apply\b')
    assert 'terraform' in command(gate, agent)
    assert tool(gate, agent, 'run_shell', {'command': 'terraform apply'}).startswith('gate: ')
    old = SimpleNamespace(host=SimpleNamespace(roots=[str(tmp_path)]))
    assert 'ask_user' in tool(gate, old, 'run_shell', {'command': 'rm -rf x'})
    assert turn(gate, old, 'release') == 'gate: release checklist not confirmed'
