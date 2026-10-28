"One key table: the key card, the tips and Sanketa's keymap file come from `KEYMAP`, every chord in it is handled, and the card names only keys that reach ramabana in Leela and tmux."
import asyncio, inspect, json, os, re, threading

from teleprint.compositor import Compositor
from teleprint.keys import Key

from ramabana import cli
from ramabana.testing import fake_agent
from test_cli_keys import _keys_scene
from ramabana.control import control_path
from test_peers import PipeTty, _cfg, _until


_NAMED = {'enter', 'escape', 'tab', 'backspace', 'delete', 'space', 'up', 'down', 'left', 'right',
          'home', 'end', 'pageup', 'pagedown', *[f'f{i}' for i in range(1, 13)]}

def leela_chord(k):
    "Leela's `parse_key`, copied from leela/core/keys.py: the grammar Sanketa renders chords with."
    *mods, base = k.split('+')
    mods = {m.lower() for m in mods}
    if 'hyper' in mods: mods = (mods - {'hyper'}) | {'mod', 'ctrl', 'alt', 'shift'}
    if base.lower() in _NAMED: base = base.lower()
    elif len(base) == 1 and base.isupper(): mods, base = mods | {'shift'}, base.lower()
    bad = mods - {'mod', 'ctrl', 'alt', 'shift'}
    if bad: raise ValueError(f'unknown modifier(s) {sorted(bad)} in {k!r}')
    if base not in _NAMED and len(base) != 1: raise ValueError(f'unknown base key {base!r} in {k!r}')
    return frozenset(mods), base


def _contexts(row): return [c] if isinstance(c := row.get('context', []), str) else c


def test_the_card_and_the_keymap_file_follow_the_table(monkeypatch):
    assert cli.HELP == cli.help_text() and {r['card'] for r in cli.KEYMAP} <= set(cli.CARD), 'every row has a line on the card'
    rows = [dict(r) for r in cli.KEYMAP]
    next(r for r in rows if r['action'] == 'fold')['label'] = 'fold the working rows like an accordion'
    monkeypatch.setattr(cli, 'KEYMAP', rows)
    assert 'ctrl+o fold the working rows like an accordion' in cli.help_text()
    keys = {r['action']: r for r in cli.keymap_doc()['keys']}
    assert keys['fold']['label'].lower() == 'fold the working rows like an accordion' and 'card' not in keys['fold']


# keys teleprint handles below the surface: the transcript view's moves, and the composer's line editing
TELEPRINT_KEYS = {'pageup', 'pagedown', 'ctrl+a', 'ctrl+e', 'ctrl+u', 'ctrl+k', 'ctrl+w', 'ctrl+y'}
KNOWN = {'alt+enter', 'alt+up', 'up', 'ctrl+c', 'ctrl+l', 'ctrl+o', 'ctrl+r', 'ctrl+t', 'shift+tab', '?'}


def _handled():
    "Every key name the surface's key layers and the task list compare against, read from their source."
    layers = (cli._core_on_key, cli._core_on_key_files, cli._ui_on_key, cli.Ui.on_key, cli.TaskMenu.choose)
    src = ''.join(inspect.getsource(f) for f in layers)
    found = {n for m in re.finditer(r"\b(?:k\.name|key(?:\.lower\(\))?)\s*(?:==|in)\s*(\([^)]*\)|'[^']*')", src)
             for n in re.findall(r"'([^']*)'", m.group(1))}
    return found | {cli.TASKS_KEY} | {f'alt+{i}' for i in range(1, 10)}


def test_every_chord_in_the_table_is_handled_and_every_handled_chord_has_a_row():
    keys = [r for r in cli.KEYMAP if not r.get('command')]
    chords = {c for r in keys for c in r['chords']}
    assert KNOWN <= chords, KNOWN - chords
    handled = _handled()
    assert handled <= chords, f'handled with no row: {handled - chords}'
    named = {c for c in chords if len(c) > 1}
    assert named <= handled | TELEPRINT_KEYS, f'a row names a key nothing handles: {named - handled - TELEPRINT_KEYS}'
    typed = [(r, c) for r in keys for c in r['chords'] if len(c) == 1]
    async def body(u, agent, tty):
        for row, c in typed:
            where = (_contexts(row) or ['idle'])[0]
            if where == 'approval':
                threading.Thread(target=lambda: agent.approvals.request('create_file', {'path': '/proj/a.md', 'text': 'x'}), daemon=True).start()
                for _ in range(100):
                    await asyncio.sleep(.01)
                    if u.ask is not None: break
                assert u.ask is not None
            if where == 'transcript': u.enter_transcript()
            if where == 'tasks': u.menu = cli.TaskMenu(lambda: [dict(kind='watch', id='w1', label='src', state='running', detail='watching src')])
            out = u.on_key(Key(c, c))
            if asyncio.iscoroutine(out): out.close()
            assert c not in u.buf.text, f'{c!r} ({row["action"]}, {where}) was typed into the composer'
            if u.ask is not None: u.answer(False)
            if u.transcript.active: u.transcript.search = None; u.leave_transcript()
            u.menu = None; u.buf.clear()
    _keys_scene(body)


def test_the_card_names_alt_enter_to_queue_and_never_shift_enter():
    queue = next(r for r in cli.KEYMAP if r['action'] == 'queue')
    assert queue['chords'] == ['alt+enter', 'shift+enter'], 'shift+enter still queues where a terminal sends it, after alt+enter'
    assert 'alt+enter queue' in cli.HELP and 'alt+enter queues' in cli.HINTS['running']
    for text in (cli.HELP, cli.GUIDE, *cli.HINTS.values(), *cli.TIPS): assert 'shift+enter' not in text, text


def _start(monkeypatch):
    "Start a terminal session and quit it at once, with ctrl+d on its empty prompt."
    tty = PipeTty(80, 24)
    monkeypatch.setattr(cli, 'AppTty', lambda: tty)
    monkeypatch.setattr(Compositor, '_register_signals', lambda self: None)
    agent = fake_agent(cfg=_cfg())[0]
    async def go():
        async def quit_when_up():
            try: await _until(control_path(agent).exists, 'the session to start')
            finally: os.write(tty.w, b'\x04')
        asyncio.get_running_loop().create_task(quit_when_up())
        await asyncio.wait_for(cli.amain(agent, pane='off'), 10)
    try: asyncio.run(go())
    finally: tty.close()


def test_a_session_writes_its_keymap_file_for_sanketa(tmp_path, monkeypatch):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.delenv('SANKETA_KEYMAPS', raising=False)
    _start(monkeypatch)
    assert not (home/'.config'/'sanketa').exists(), 'no Sanketa folder, nothing written'
    folder = tmp_path/'keymaps'
    monkeypatch.setenv('SANKETA_KEYMAPS', str(folder))
    _start(monkeypatch)
    f = folder/'ramabana.json'
    doc = json.loads(f.read_text())
    assert doc['version'] == 1 and doc['app'] == 'ramabana' and doc['name'] and doc['written_by'].startswith('ramabana ')
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', doc['written_at']) and 'overrides' not in doc
    assert doc['app_version'] == cli.__version__ and doc['written_by'] == f'ramabana {doc["app_version"]}'
    ids = [c['id'] for c in doc['contexts']]
    assert {'idle', 'typing', 'running', 'waiting', 'approval', 'python', 'transcript'} <= set(ids)
    actions = [r['action'] for r in doc['keys']]
    assert len(actions) == len(set(actions)) == len(cli.KEYMAP)
    for r in doc['keys']:
        assert r['chords'] and r['label'] and set(_contexts(r)) <= set(ids), r
        if not r.get('command'): [leela_chord(c) for c in r['chords']]
    when = f.stat().st_mtime_ns
    _start(monkeypatch)
    assert f.stat().st_mtime_ns == when, 'the same keys are not written again'
    rows = [dict(r) for r in cli.KEYMAP]
    rows[0]['label'] = 'a changed label'
    monkeypatch.setattr(cli, 'KEYMAP', rows)
    assert cli.write_keymap() == f and json.loads(f.read_text())['keys'][0]['label'] == 'A changed label'
    f.write_text('{"version": 1, "app": "ramabana", "keys": []}')
    assert cli.write_keymap() is None and json.loads(f.read_text())['keys'] == [], "a file ramabana did not write is left alone"
    monkeypatch.setenv('SANKETA_KEYMAPS', str(f))
    assert cli.write_keymap() is None, 'a folder that cannot be written is no error'
    monkeypatch.delenv('SANKETA_KEYMAPS')
    (home/'.config'/'sanketa').mkdir(parents=True)
    assert cli.write_keymap() == home/'.config'/'sanketa'/'keymaps'/'ramabana.json'
