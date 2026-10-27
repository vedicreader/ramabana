"config.toml: one hand-edited file per machine. A flag beats an env var, an env var beats the file, the file beats the default."
import json, os, sys, warnings
import pytest
from ramabana import setup
from ramabana.core import Routing, accepts, resolve
from ramabana.learned import enabled, set_enabled
from ramabana.runtime import RishiBackend, img_tokens, margin, threshold
from ramabana.setup import config_path, launch_args, load_config, set_setting, setting


def _write(text): config_path().write_text(text); return config_path()


def test_precedence_env_beats_the_file_and_the_file_beats_the_default(monkeypatch):
    for k in ('RAMABANA_MODEL', 'LEELA_MODEL', 'RAMABANA_MODEL_SUMMARY', 'LEELA_MODEL_SUMMARY'): monkeypatch.delenv(k, raising=False)
    test = Routing()
    assert not test.own('summary')
    _write('[jobs]\nturn = "gpt-5.4"\nsummary = "gpt-5.4-mini"\n')
    r = Routing()
    assert r.turn == 'gpt-5.4' and r.name_for('summary') == 'gpt-5.4-mini' and r.own('summary')
    monkeypatch.setenv('RAMABANA_MODEL', 'gpt-4.1'); monkeypatch.setenv('RAMABANA_MODEL_SUMMARY', 'gpt-4.1-mini')
    r = Routing()
    assert r.turn == 'gpt-4.1' and r.name_for('summary') == 'gpt-4.1-mini'
    assert Routing(turn='gpt-5.6').turn == 'gpt-5.6', 'a flag, passed as the turn, beats both'


def test_the_cli_takes_its_defaults_from_the_file_and_a_flag_still_wins(monkeypatch):
    _write('[cli]\napprove = "auto"\ntmux = "off"\nmax_steps = 40\n')
    seen = {}
    def fake(prompt: str = '', approve: str = 'ask', max_steps: str = 'auto', tmux: str = 'auto'): pass
    class Main:
        __wrapped__ = staticmethod(fake)
        def __call__(self, **kw): seen.update(kw); return 0
    import ramabana.cli
    monkeypatch.setattr(ramabana.cli, 'main', Main())
    monkeypatch.setattr(sys, 'argv', ['ramabana', '--approve', 'ask', 'hi'])
    assert setup.run_cli() == 0
    assert seen == dict(prompt='hi', approve='ask', max_steps='40', tmux='off'), seen
    assert launch_args(['--root', '.']) is None, 'tmux = "off" keeps the session out of tmux'
    assert launch_args(['--tmux', 'on'])['tmux'] == 'on', 'the flag wins'


def test_every_palette_is_a_cli_theme_and_an_unknown_name_warns_and_takes_auto(monkeypatch):
    from ramabana.cli import THEMES
    assert set(setup.KEYS['cli.theme'].choices) == {'auto', *THEMES}
    seen = {}
    def fake(prompt: str = '', approve: str = 'ask', theme: str = 'auto'): pass
    class Main:
        __wrapped__ = staticmethod(fake)
        def __call__(self, **kw): seen.update(kw); return 0
    import ramabana.cli
    monkeypatch.setattr(ramabana.cli, 'main', Main())
    monkeypatch.setattr(sys, 'argv', ['ramabana', 'hi'])
    _write('[cli]\ntheme = "gruvbox"\napprove = "auto"\n')
    assert setup.run_cli() == 0 and seen == dict(prompt='hi', approve='auto', theme='gruvbox'), seen
    _write('[cli]\ntheme = "no-such"\napprove = "auto"\n')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        assert setup.run_cli() == 0
    assert seen == dict(prompt='hi', approve='auto', theme='auto'), 'the other cli defaults stay'
    assert [str(x.message) for x in w if 'cli.theme' in str(x.message)] and len(w) == 1, [str(x.message) for x in w]


def test_run_cli_hands_config_to_its_own_command_before_parsing_a_prompt(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['ramabana', 'config', 'path'])
    assert setup.run_cli() == 0 and capsys.readouterr().out.strip() == str(config_path())
    monkeypatch.setattr(sys, 'argv', ['ramabana', 'config', 'init'])
    assert setup.run_cli() == 0 and config_path().read_text().startswith('# Ramabana')
    monkeypatch.setattr(sys, 'argv', ['ramabana', 'config', 'show'])
    assert setup.run_cli() == 0 and 'window.margin' in capsys.readouterr().out


def test_calm_is_a_boolean_key_that_is_off_until_the_file_turns_it_on():
    assert setting('calm', False) is False and setup.config_defaults()['calm'] is False
    assert '# calm = false' in setup.config_template()
    _write('calm = true\n')
    assert setting('calm', False) is True
    _write('calm = "yes"\n')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        assert setting('calm', False) is False and len(w) == 1


def test_a_per_model_window_reaches_the_guard():
    name = 'openai/gpt-5.4'
    upstream = resolve(name)
    _write(f'[model."{name}"]\nmax_input_tokens = 9000\nmax_output_tokens = 2000\nsupports_images = false\n')
    spec = resolve(name)
    assert (spec.ctx, spec.opts['max_output_tokens'], accepts(spec, 'image')) == (9000, 2000, False) and upstream.ctx != 9000
    be = RishiBackend(spec)
    be._used = 9000 - 1024 - 10
    assert not be.fits('x' * 400), 'the guard sizes the turn against the corrected window'
    assert be._runtime_kw()['max_output_tokens'] == 2000


def test_the_guard_knobs_are_read_each_time():
    _write('[window]\nmargin = 1.3\nimage_tokens = 2000\nreserve = 1000\n')
    assert (margin(), img_tokens(), threshold(100_000)) == (1.3, 2000, 99_000)


def test_invalid_entries_warn_and_take_their_defaults():
    _write('lerning = false\n[window]\nmargin = "big"\nimage_tokens = -3\n[cli]\napprove = "sometimes"\n[model."x/y"]\nmax_input_tokens = true\n')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        vals, bad = load_config()
    assert vals == {} and len(bad) == 5 and len(w) == 5
    assert margin() == 1.15 and img_tokens() == 1600
    _write('[window\n')
    assert load_config()[0] == {} and load_config()[1] and margin() == 1.15


def test_a_problem_in_the_file_is_one_of_the_agents_problems():
    from ramabana.agent import Agent
    from ramabana.testing import MemHost
    _write('[window]\nmargin = 0\n')
    a = Agent(MemHost({'/proj/a.py': ''}), extensions=False)
    assert any('margin = 0 is ignored' in p for p in a.problems)


def test_learning_moves_from_settings_json_and_leaves_that_file_alone(tmp_path):
    cfg = tmp_path/'leela'; cfg.mkdir()
    shared = {'editor': {'tabSize': 2}, 'theme': 'dusk', 'learning': 'off'}
    (cfg/'settings.json').write_text(json.dumps(shared))
    assert not config_path().exists() and enabled(cfg) is False
    assert setting('learning') is False and '\nlearning = false\n' in config_path().read_text()
    assert json.loads((cfg/'settings.json').read_text()) == shared, "the shared settings.json is never written"
    assert set_enabled(cfg, True) and enabled(cfg) and enabled(tmp_path/'elsewhere'), 'one switch per machine'
    assert json.loads((cfg/'settings.json').read_text()) == shared


def test_the_shared_folder_is_never_where_config_goes(tmp_path):
    "An embedding app's folder holds its own settings.json; config.toml stays this machine's one file."
    cfg = tmp_path/'app'; cfg.mkdir(); (cfg/'settings.json').write_text('{not json')
    set_enabled(cfg, False)
    assert sorted(p.name for p in cfg.iterdir()) == ['settings.json'] and (cfg/'settings.json').read_text() == '{not json'
    assert enabled(cfg) is False


def test_a_file_that_is_not_toml_is_never_rewritten():
    p = _write('# mine\nlearning = [\n')
    with pytest.raises(ValueError, match='not valid TOML'): set_setting('learning', True)
    assert p.read_text() == '# mine\nlearning = [\n'
    from ramabana.learned import learned_command
    assert 'not valid TOML' in learned_command(p.parent/'learned', 'off')


def test_a_read_only_home_keeps_answering(tmp_path, monkeypatch):
    cfg = tmp_path/'c'; cfg.mkdir(); (cfg/'settings.json').write_text(json.dumps({'learning': 'off'}))
    monkeypatch.setenv('RAMABANA_CONFIG', str(tmp_path/'ro'/'config.toml'))
    (tmp_path/'ro').mkdir(); os.chmod(tmp_path/'ro', 0o500)
    try: assert enabled(cfg) is False
    finally: os.chmod(tmp_path/'ro', 0o700)
