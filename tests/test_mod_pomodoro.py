import importlib.util
from pathlib import Path
from shalya.skills import Registry, check

POMO = Path(__file__).parents[1]/'examples'/'mods'/'pomodoro.py'


def load():
    spec = importlib.util.spec_from_file_location('pomodoro', POMO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start(pomo, home):
    "A registry with the mod set up as a mod whose home is `home`."
    reg = Registry()
    reg.add_mod('pomodoro', pomo.setup, home=home)
    assert reg.mods[0].on, reg.mods[0].note
    return reg


def timer_of(reg, seconds):
    return [t for t in reg.timers if t.seconds == seconds][-1]


def test_check_lists_registrations():
    info = check(POMO)
    assert 'pomo' in info['commands']
    assert info['hooks'] == {'before_turn': 1}
    assert len(info['status']) == 1
    assert dict(seconds=60, repeat=True) in info['timers']


def test_block_break_refusal_and_stop(tmp_path):
    pomo = load()
    clock = [1000.0]
    pomo.now = lambda: clock[0]
    reg = start(pomo, tmp_path)
    run, status = reg.commands['pomo'][0], reg.status_segments[0]

    def refusals(prompt): return [out for out in reg.fire('before_turn', None, prompt) if out]

    assert run(None, '3') == 'Focus block started: 3 min.'
    assert run(None, '') == 'pomo: 3 min left.'
    assert status(None) == 'pomo 3m'
    clock[0] += 61
    assert status(None) == 'pomo 2m'
    assert refusals('hi') == []
    timer_of(reg, 180).callback()
    assert [n['text'] for n in reg.drain_notices()] == ['Pomodoro done. Take a 5-minute break.']
    assert status(None) == 'break 5m'
    clock[0] += 60
    assert refusals('fix the bug') == ['pomodoro: on a break, 4 min left']
    assert refusals('!fix the bug') == []
    timer_of(reg, 300).callback()
    assert [n['text'] for n in reg.drain_notices()] == ['Break over.']
    assert status(None) is None

    assert run(None, '10') == 'Focus block started: 10 min.'
    block = timer_of(reg, 600)
    assert run(None, 'stop') == 'Stopped.'
    assert block.cancelled
    assert not any(t.seconds == 600 for t in reg.timers)
    block.callback()
    assert reg.drain_notices() == []
    for t in list(reg.timers): t.cancel()


def test_block_survives_reload(tmp_path):
    pomo = load()
    clock = [1000.0]
    pomo.now = lambda: clock[0]
    reg = start(pomo, tmp_path)
    reg.commands['pomo'][0](None, '10')
    clock[0] += 60
    reg = start(pomo, tmp_path)
    assert reg.status_segments[0](None) == 'pomo 9m'
    assert reg.commands['pomo'][0](None, '') == 'pomo: 9 min left.'
    timer_of(reg, 540).callback()
    reg = start(pomo, tmp_path)
    assert reg.status_segments[0](None) == 'break 5m'
    reg.commands['pomo'][0](None, 'stop')
    assert start(pomo, tmp_path).status_segments[0](None) is None
    clock[0] += 1000
    reg.commands['pomo'][0](None, '5')
    clock[0] += 400
    assert start(pomo, tmp_path).status_segments[0](None) is None
    for t in list(reg.timers): t.cancel()
