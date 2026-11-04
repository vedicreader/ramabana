"A vesha: mods and config keys started by name, layered between config.toml and the env vars and flags."
import sys
import pytest
from ramabana import cli, setup
from ramabana.core import Routing
from ramabana.setup import config_path, config_show, load_vesha, setting, use_vesha, vesha_dir
from ramabana.testing import fake_agent

HELLO = r'''
def setup(reg): reg.command('hello', lambda agent, arg: 'hi there')
'''


@pytest.fixture(autouse=True)
def veshas(monkeypatch):
    "config.toml, a `base` vesha and a `deep` one that extends it; no vesha active before or after."
    monkeypatch.setattr(setup, 'VESHA', None)
    for k in ('RAMABANA_MODEL', 'LEELA_MODEL'): monkeypatch.delenv(k, raising=False)
    config_path().write_text('[cli]\napprove = "edits"\nhints = true\n\n[jobs]\nturn = "gpt-5.4"\n')
    vesha_dir().mkdir()
    (vesha_dir()/'base.toml').write_text('description = "Base"\n\n[jobs]\nturn = "gpt-5.4-mini"\n')
    (vesha_dir()/'deep.toml').write_text('description = "Deep work"\nextends = "base"\nmods = ["hello"]\n\n[cli]\napprove = "ask"\n')


def _run(monkeypatch, *argv):
    "What `run_cli` hands `main` for `argv`, with `main` replaced by a recorder."
    seen = {}
    def fake(prompt: str = '', approve: str = 'ask', vesha: str = '', hints: bool = True, read_outside: bool = False, vault: bool = False,
             pii: str = 'off', no_read_outside: bool = False, no_vault: bool = False): pass
    class Main:
        __wrapped__ = staticmethod(fake)
        def __call__(self, **kw): seen.update(kw); return 0
    monkeypatch.setattr(cli, 'main', Main())
    monkeypatch.setattr(sys, 'argv', ['ramabana', *argv])
    return setup.run_cli(), seen


def test_a_vesha_lies_over_config_toml_under_the_env_and_the_flags(monkeypatch):
    code, seen = _run(monkeypatch, '--vesha', 'deep', 'hi')
    assert code == 0 and (seen['approve'], seen['hints'], seen['vesha']) == ('ask', True, 'deep'), seen
    assert setting('jobs.turn') == 'gpt-5.4-mini' and Routing().turn == 'gpt-5.4-mini', 'base, through the extends chain'
    monkeypatch.setenv('RAMABANA_MODEL', 'gpt-4.1')
    assert Routing().turn == 'gpt-4.1', 'an env var beats the vesha'
    assert _run(monkeypatch, '--vesha', 'deep', '--approve', 'auto', 'hi')[1]['approve'] == 'auto', 'a flag beats the vesha'
    assert _run(monkeypatch, 'hi')[1]['approve'] == 'edits' and setting('jobs.turn') == 'gpt-5.4', 'no vesha, no layer'
    config_path().write_text(config_path().read_text().replace('hints = true', 'hints = true\nvesha = "deep"'))
    assert _run(monkeypatch, 'hi')[1]['approve'] == 'ask', 'cli.vesha in config.toml picks one too'


def test_config_show_names_the_vesha_that_set_each_key(monkeypatch):
    monkeypatch.delenv('RAMABANA_MODEL', raising=False)
    rows = config_show(vesha='deep').splitlines()
    assert '# vesha deep' in rows
    assert any(r.startswith('cli.approve = "ask"   # vesha deep') for r in rows), rows
    assert any(r.startswith('jobs.turn = "gpt-5.4-mini"   # vesha base') for r in rows), rows
    assert any(r.startswith('cli.hints = true   # config.toml') for r in rows), rows
    use_vesha('deep')
    assert config_show() == '\n'.join(rows), 'the active vesha is the one shown'


def test_a_vesha_may_tighten_permissions_but_loosening_one_stops_start_up(monkeypatch, capsys):
    (vesha_dir()/'strict.toml').write_text('[cli]\napprove = "off"\npii = "refuse"\n')
    assert _run(monkeypatch, '--vesha', 'strict', 'hi')[1]['approve'] == 'off'
    (vesha_dir()/'loose.toml').write_text('extends = "deep"\n\n[cli]\napprove = "auto"\n')
    assert _run(monkeypatch, '--vesha', 'loose', 'hi')[0] == 2
    err = capsys.readouterr().err
    for bit in ('vesha loose', 'cli.approve', '"auto"', '"edits"', 'config.toml', '--approve'): assert bit in err, (bit, err)
    assert _run(monkeypatch, '--vesh', 'loose', 'hi')[0] == 2, 'an abbreviated --vesha is checked too'
    capsys.readouterr()
    assert _run(monkeypatch, '--vesha', 'loose', '--approve', 'auto', 'hi')[1]['approve'] == 'auto', 'a flag still wins'
    (vesha_dir()/'reach.toml').write_text('[cli]\nread_outside = true\n')
    assert _run(monkeypatch, '--vesha', 'reach', 'hi')[0] == 2
    err = capsys.readouterr().err
    assert 'vesha reach' in err and 'cli.read_outside' in err and '--read-outside' in err, err
    config_path().write_text('[cli]\nvault = true\npii = "redact"\n')
    (vesha_dir()/'bare.toml').write_text('[cli]\npii = "off"\n')
    assert _run(monkeypatch, '--vesha', 'bare', 'hi')[0] == 2 and 'cli.pii' in capsys.readouterr().err


def test_an_unknown_vesha_a_cycle_or_a_bad_key_stops_start_up_with_the_valid_names(monkeypatch, capsys):
    assert _run(monkeypatch, '--vesha', 'nope', 'hi')[0] == 2
    err = capsys.readouterr().err
    assert "unknown vesha 'nope'" in err and 'base, deep' in err, err
    (vesha_dir()/'a.toml').write_text('extends = "b"\n'); (vesha_dir()/'b.toml').write_text('extends = "a"\n')
    with pytest.raises(ValueError, match='cycle: a -> b -> a'): load_vesha('a')
    (vesha_dir()/'typo.toml').write_text('[cli]\nhintz = false\n')
    with pytest.raises(ValueError, match='did you mean cli.hints.*valid keys: .*cli.approve'): load_vesha('typo')
    assert load_vesha('deep').mods == ('hello',) and load_vesha('base').mods is None
    config_path().write_text('[cli]\nvesha = "gone"\n')
    assert _run(monkeypatch, 'hi')[0] == 2
    with pytest.raises(SystemExit) as stopped: _run(monkeypatch, '--help')
    assert stopped.value.code == 0, '--help still runs, so the vesha can be fixed'


def test_the_cli_hands_no_mods_and_the_vesha_mods_to_the_agent(monkeypatch):
    from fastcore.script import anno_parser
    made = {}
    def build(roots, **kw):
        made.update(kw)
        raise RuntimeError('built')
    monkeypatch.setattr(cli, 'mk_agent', build)
    monkeypatch.setattr(cli.setup, 'LAUNCHED', True)
    def main(*argv):
        args = vars(anno_parser(cli.main.__wrapped__, pos=['prompt']).parse_args(['go', '--approve', 'auto', *argv]))
        for k in ('pdb', 'xtra'): args.pop(k, None)
        return cli.main(**args)
    assert main('--no-mods') == 2 and (made['extensions'], made['mods']) == (False, None), made
    assert main('--vesha', 'deep') == 2 and (made['extensions'], made['mods'], made['vesha']) == (True, ('hello',), 'deep'), made
    assert main('--vesha', 'nope') == 2


def test_slash_vesha_lists_the_veshas_and_switches_the_mods(tmp_path):
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods'/'hello.py').write_text(HELLO)
    a, _ = fake_agent(cfg=tmp_path, extensions=True, mods=())
    assert a.command('/hello') is None and 'vesha' not in a.status()
    assert a.command('/vesha').splitlines() == ['  base', '  deep']
    said = a.command('/vesha deep')
    assert 'mods on: hello' in said and 'next starts' in said, said
    assert a.command('/hello') == 'hi there' and a.status()['vesha'] == 'deep' and '* deep' in a.command('/vesha')
    assert a.command('/vesha nope').startswith("unknown vesha 'nope'")
