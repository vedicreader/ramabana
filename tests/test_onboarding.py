"A first run: the turn moves to a model that is ready when nobody named one, and jobs without a model of their own follow it. Nothing here calls the network."
import asyncio, os
import pytest
from teleprint.compositor import Compositor
import ramabana.cli as cli
from ramabana import core
from ramabana.core import DFLT_TURN, JOBS, Routing, auth_status, getting_started, ready_turn, welcome
from ramabana.testing import fake_agent
from test_cli_pane import PipeTty
from ramabana.models import CATALOG
from ramabana.setup import config_path

KEYS = ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK')

@pytest.fixture
def machine(monkeypatch):
    "A machine with nothing set up; `ready(...)` turns providers on."
    seen = dict(claude=False, codex=False, copilot=False)
    monkeypatch.setattr(core, '_claude_available', lambda: seen['claude'])
    monkeypatch.setattr(core, '_claude_login', lambda: seen['claude'])
    monkeypatch.setattr(core, '_claude_signed_out', lambda: False)
    monkeypatch.setattr(core, '_codex_login', lambda: seen['codex'])
    monkeypatch.setattr(core, '_copilot_available', lambda: seen['copilot'])
    monkeypatch.setattr(core, 'copilot_catalog', lambda ttl=300: {m: {'capabilities': {'type': 'chat'}} for m in ('gpt-6-sol', 'claude-sonnet-5-5')})
    for k in KEYS: monkeypatch.delenv(k, raising=False)
    for p in ('RAMABANA_', 'LEELA_'):
        for j in ('', *(f'_{j.upper()}' for j in JOBS)): monkeypatch.delenv(f'{p}MODEL{j}', raising=False)
    def ready(*names, **env):
        for n in names: seen[n] = True
        for k, v in env.items(): monkeypatch.setenv(k, v)
    return ready


def test_a_turn_nobody_named_moves_to_the_first_ready_provider(machine, monkeypatch):
    r = Routing()
    assert ready_turn() == '' and r.settled() == '' and r.turn == DFLT_TURN, 'with nothing ready the turn stays put, for the welcome to explain'
    machine(OPENAI_API_KEY='k', GEMINI_API_KEY='k')
    assert ready_turn() == f'openai/{CATALOG["openai"][0]}', 'an OpenAI key beats a Gemini key'
    machine('copilot')
    assert ready_turn() == 'copilot/claude-sonnet-5-5', 'a subscription beats a key, and Claude ids lead among what Copilot offers'
    machine('codex')
    assert ready_turn() == f'codex/{CATALOG["codex"][0]}'
    r = Routing()
    assert r.settled() == ready_turn() and r.turn == DFLT_TURN, 'settled names the move; the agent makes it'
    r.turn = ready_turn()
    assert r.settled() == '', 'a turn that runs is left alone'
    machine('claude')
    assert ready_turn() == DFLT_TURN and Routing().settled() == ''
    monkeypatch.setattr(core, '_claude_signed_out', lambda: True)
    assert core.needs_setup(Routing()) == core.CLAUDE_SIGNED_OUT, 'Claude Code installed with nobody signed in cannot run a turn'


def test_a_turn_someone_named_is_never_replaced(machine, monkeypatch):
    machine(OPENAI_API_KEY='k')
    gone = 'gemini/gemini-3.5-flash'   # no GEMINI_API_KEY, so it cannot run
    assert Routing(turn=gone).settled() == '', '--model names the turn for this run'
    monkeypatch.setenv('RAMABANA_MODEL', gone)
    assert Routing().settled() == '' and Routing().turn == gone
    monkeypatch.delenv('RAMABANA_MODEL')
    config_path().write_text(f'[jobs]\nturn = "{gone}"\n')
    assert Routing().settled() == ready_turn(), 'config.toml names a default, not this run'


def test_a_job_without_a_model_of_its_own_follows_the_turn_quietly(machine):
    machine(OPENAI_API_KEY='k')
    r = Routing(turn=ready_turn())
    assert r.spec('classify').name == r.turn and 'classify' not in r.notes and r.news == []
    r.set(core.DFLT_SMALL, 'classify')
    assert r.spec('classify').name == r.turn and 'classify' in r.notes and len(r.news) == 1, 'a model someone chose says when it cannot run'


def test_the_getting_started_list_ticks_off_what_it_finds(machine, monkeypatch):
    monkeypatch.delenv('TMUX', raising=False)
    monkeypatch.setattr(core.shutil, 'which', lambda prog, *a, **kw: None)
    rows = getting_started(auth_status(), wsl=True)
    assert not rows[-1][0], 'nothing runs, so the last row is still to do'
    machine(OPENAI_API_KEY='k')
    rows = getting_started(auth_status(), wsl=False)
    assert rows[-1][0], 'a key was found, so a session can run'


def test_a_session_with_no_model_opens_on_the_welcome(machine, tmp_path, monkeypatch):
    "It used to print the setup guide and exit before the session opened."
    tty = PipeTty(100, 30)
    monkeypatch.setattr(cli, 'AppTty', lambda: tty)
    monkeypatch.setattr(Compositor, '_register_signals', lambda self: None)
    agent = fake_agent(cfg=tmp_path)[0]
    seen = {}
    async def go():
        loop = asyncio.get_running_loop()
        loop.call_later(.4, lambda: seen.update(screen=tty.term.text()))
        loop.call_later(.5, os.write, tty.w, b'\x04')
        await asyncio.wait_for(cli.amain(agent, pane='off', first=welcome(Routing()), cold=True), 10)
    asyncio.run(go())
    assert 'Welcome to Ramabana' in seen['screen'] and '/login' in seen['screen'] and 'no model available' not in seen['screen']
    tty.close()
