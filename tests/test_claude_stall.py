"A Claude Code turn that goes silent: its limit comes from config.toml, its retry shows as a status note mid-turn, and its error names the setting."
from dataclasses import replace
from ramabana.core import resolve
from ramabana.runtime import Backend, RishiBackend, Run
from ramabana.setup import config_path


def _write(text): config_path().write_text(text); return config_path()


def test_the_silence_limit_comes_from_config_toml_for_a_claude_model_only():
    _write('[model."claude-opus-5-5"]\ntimeout = 30\n\n[model."openai/gpt-5.4"]\ntimeout = 30\n')
    kw = RishiBackend(resolve('claude-opus-5-5'))._runtime_kw()
    assert kw['timeout'] == 30 and callable(kw['on_stall'])
    assert kw['timeout_hint'] == f'timeout under [model."claude-opus-5-5"] in {config_path()}'
    assert 'timeout' not in RishiBackend(resolve('openai/gpt-5.4'))._runtime_kw(), 'other runtimes take no Claude Code limit'
    assert 'timeout' not in RishiBackend(resolve('claude-sonnet-5-5'))._runtime_kw(), "no setting leaves rishi's default"


def test_the_hint_names_the_table_that_is_set():
    _write('[model."claude-opus-5-5"]\ntimeout = 30\n')
    spec = replace(resolve('claude-opus-5-5'), name='mine')
    assert '[model."claude-opus-5-5"]' in RishiBackend(spec)._runtime_kw()['timeout_hint']
    _write('')
    assert '[model."mine"]' in RishiBackend(spec)._runtime_kw()['timeout_hint']


def test_a_notice_is_the_run_status_and_reaches_the_frontend_now(monkeypatch):
    be = RishiBackend(resolve('claude-opus-5-5'))
    be.run, got = Run('r1'), []
    monkeypatch.setattr(Backend, 'on_notice', got.append)
    be.notice('Claude Code sent nothing for 240s, so the turn was ended and is being tried once more')
    assert got and be.run.status.startswith('Claude Code sent nothing') and be.problems == []
    monkeypatch.setattr(Backend, 'on_notice', None)
    be.run = None
    be.notice('again'); assert be.problems == ['again'], 'with no frontend listening it is kept as a problem'
    def boom(t): raise RuntimeError('gone')
    monkeypatch.setattr(Backend, 'on_notice', boom)
    be.notice('third'); assert be.problems[-1] == 'third', 'a failing frontend does not lose it'


def test_the_terminal_shows_a_notice_as_a_note(monkeypatch):
    from ramabana.runtime import TokenLogger
    monkeypatch.setattr(Backend, 'on_notice', None); monkeypatch.setattr(TokenLogger, 'sink', None)
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    from ramabana.testing import fake_agent
    tty = EmuTty(80, 24); comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    ui = Ui(comp, fake_agent()[0])
    Backend.on_notice('Claude Code sent nothing for 240s')
    assert any('sent nothing for 240s' in (b.source or str(getattr(b, 'body', ''))) for b in comp.blocks.values())
    tty.close()
