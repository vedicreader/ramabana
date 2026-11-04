import importlib.util
from pathlib import Path
from fastcore.basics import AttrDict
from rich.cells import cell_len
from shalya.skills import Registry, check

WEATHER = Path(__file__).parents[1]/'examples'/'mods'/'weather'
AGENT = AttrDict(status=lambda: {'pct_full': 0.34})


def registry():
    spec = importlib.util.spec_from_file_location('weather', WEATHER/'mod.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    reg = Registry()
    mod.setup(reg)
    return reg


def test_check_lists_registrations():
    info = check(WEATHER)
    assert info['commands'] == ['weather']
    assert info['hooks'] == {'after_tool': 1, 'after_turn': 1}
    assert len(info['status']) == 1
    assert info['bands'] == [dict(rows=2)]


def test_turns_failures_and_band():
    reg = registry()
    reg.fire('after_tool', AGENT, 'read', 'ok')
    reg.fire('after_tool', AGENT, 'shell', 'ERROR: exit 1')
    reg.fire('after_tool', AGENT, 'read', 'ok')
    reg.fire('after_turn', AGENT, 'done')
    reg.fire('after_turn', AGENT, 'chat')
    assert 'Failed calls: 1' in reg.commands['weather'][0](AGENT, '')
    band = reg.bands[0]
    assert band(AttrDict(busy=True, width=80)) is None
    row = band(AttrDict(busy=False, width=80))[0]
    assert [text for text, _ in row[1:]] == ['█', '▁']
    assert [style for _, style in row[1:]] == ['red', '#6a9955']


def test_status_thresholds():
    status = registry().status_segments[0]
    for pct, word in [(0.34, 'clear'), (0.5, 'cloudy'), (0.8, 'cloudy'), (0.81, 'storm')]:
        assert status(AttrDict(status=lambda pct=pct: {'pct_full': pct})).startswith(f'ctx {word} ')
    assert status(AttrDict(status=lambda: {'pct_full': 0.344})) == 'ctx clear 34%'
    assert status(AttrDict(status=lambda: {'pct_full': 1.7})) == 'ctx storm 100%'
    assert status(object()) is None
    assert status(AttrDict(status=lambda: {})) is None


def test_band_fits_width_and_caps_history():
    reg = registry()
    band = reg.bands[0]
    assert band(AttrDict(busy=False, width=80)) is None
    for _ in range(25): reg.fire('after_turn', AGENT, 'x')
    row = band(AttrDict(busy=False, width=80))[0]
    assert len(row) - 1 == 20
    row = band(AttrDict(busy=False, width=12))[0]
    assert cell_len(''.join(text for text, _ in row)) <= 12
