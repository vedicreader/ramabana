"What `<cfg>/learned` may put in a briefing, and the start state a resumed session leaves alone."
from ramabana.core import ModelSpec
from ramabana.testing import fake_agent
from ramabana.tools import find

BIG = ModelSpec('fake', 'fake', 'fake/model', ctx=200_000)   # a window that inlines skills


def test_a_resumed_session_without_a_start_file_writes_none(tmp_path):
    "Its first turn is gone: the state now is not the state it began from, and Dhrona would replay from it."
    a, _ = fake_agent(cfg=tmp_path, replies=['ok'])
    a.history = [{'at': 0, 'session': 's1', 'prompt': 'read a.py', 'reply': 'done', 'model': '', 'activity': []}]
    a.resume_session('s1')
    a.ask('and again')
    assert not (tmp_path/'runs'/'s1'/'start.json').exists()


def test_a_new_session_writes_its_start_file(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, replies=['ok'])
    a.ask('read a.py')
    assert (tmp_path/'runs'/a.session_id/'start.json').read_text().strip() == '[]'   # MemHost's folder is no repository


def test_a_learned_skill_inlined_is_clipped_to_the_learned_cap(tmp_path):
    "A learned skill in an inline skill's name replaces it, inlined; whole, it would put any length of text in every briefing."
    from ramabana.agent import MAX_CONTEXT_FILE
    d = tmp_path/'learned'/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: hash-addressed edits\n---\nLEARNED-BODY ' + 'x' * 50_000)
    a, _ = fake_agent(cfg=tmp_path, optin=('exhash',))   # `edit_file` offered, so `exhash` is inlined
    a.routing.spec = lambda job='turn', fallback=True: BIG
    sp = a.system_prompt()
    assert 'LEARNED-BODY' in sp and 'x' * (MAX_CONTEXT_FILE + 1) not in sp and 'read_skill("exhash")' in sp
    assert len(find(a.skills, 'exhash').text()) > MAX_CONTEXT_FILE * 2   # read on demand, to shalya's own clip


def test_the_installed_skill_is_inlined_whole(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, optin=('exhash',))
    a.routing.spec = lambda job='turn', fallback=True: BIG
    assert find(a.skills, 'exhash').text() in a.system_prompt()


def test_a_session_built_on_an_old_id_writes_no_start_file(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, replies=['ok'], session_id='s1')
    a.history = [{'at': 0, 'session': 's1', 'prompt': 'read a.py', 'reply': 'done', 'model': '', 'activity': []}]
    a.ask('and again')
    assert not (tmp_path/'runs'/'s1'/'start.json').exists()


def test_a_start_file_is_kept(tmp_path):
    a, _ = fake_agent(cfg=tmp_path, replies=['ok'])
    (p := tmp_path/'runs'/a.session_id/'start.json').parent.mkdir(parents=True)
    p.write_text('[{"repo": "/r"}]')
    a.ask('read a.py')
    assert p.read_text() == '[{"repo": "/r"}]'


def test_lessons_read_back_from_the_memory_file(tmp_path):
    "The no-vault layout, read by the same shalya reader Dhrona uses."
    a, _ = fake_agent(cfg=tmp_path)
    rem = next(t for t in a.tools if t.__name__ == 'remember')
    rem('filter on the root-relative path', cue='an empty filtered search', component='tool', confidence='high')
    rem('a plain note')
    assert a.lessons() == [dict(lesson='filter on the root-relative path', cue='an empty filtered search', component='tool', confidence='high')]


def test_lessons_read_back_from_a_vault(tmp_path):
    from shalya.tools import lesson_text
    from ramabana.testing import MemHost
    t = lesson_text('use ls', cue='sizes', component='skill')
    class Vault(MemHost):
        provides = property(lambda self: frozenset(MemHost.provides.fget(self)) | {'memory'})
        def memory_search(self, q, n): return dict(results=[dict(title=t.splitlines()[0], text=t), dict(title='x', text='a plain note')])
    a, _ = fake_agent(Vault({'/proj/a.py': ''}), cfg=tmp_path)
    assert a.lessons() == [dict(lesson='use ls', cue='sizes', component='skill')]


def _propose(folder, files, id):
    "What Dhrona's `keep` does: a commit on `pending/<id>` off HEAD, the folder's files untouched."
    import subprocess, tempfile
    from pathlib import Path
    def git(d, *a): return subprocess.run(['git', '-C', str(d), *a], check=True, capture_output=True, text=True).stdout.strip()
    if not (folder/'.git').exists():
        folder.mkdir(parents=True, exist_ok=True)
        git(folder, 'init', '-q'); git(folder, '-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-q', '--allow-empty', '-m', 'first')
    wt = Path(tempfile.mkdtemp())/'wt'
    git(folder, 'worktree', 'add', '-q', '-b', f'pending/{id}', str(wt), 'HEAD')
    for rel, text in files.items(): (wt/rel).parent.mkdir(parents=True, exist_ok=True); (wt/rel).write_text(text)
    git(wt, 'add', '-A'); git(wt, '-c', 'user.name=Dhrona', '-c', 'user.email=d@x', 'commit', '-qm', f'Lesson from a replay: {id}')
    git(folder, 'worktree', 'remove', '--force', str(wt))


def test_the_learned_command_in_the_interface(tmp_path):
    "`/learned` lists, diffs, accepts and rejects through `ramabana.learned`, and tab completion offers it."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import HELP, Ui
    a, b = '20261019-010101-aaaaaa', '20261019-020202-bbbbbb'
    _propose(tmp_path/'learned', {'AGENTS.md': 'Read sizes from ls.\n'}, a)
    _propose(tmp_path/'learned', {'skills/x/SKILL.md': '---\nname: x\ndescription: y\n---\nz\n'}, b)
    agent, _ = fake_agent(cfg=tmp_path)
    tty = EmuTty(100, 30); comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    ui = Ui(comp, agent)
    def run(line):
        ui.buf.insert(line); ui.submit()
        return [blk.source for blk in ui.comp.blocks.values() if blk.tag == 'note'][-1]
    try:
        assert a in run('/learned') and b in run('/learned list')
        assert '+Read sizes from ls.' in run(f'/learned diff {a}')
        assert run(f'/learned accept {a}').startswith(f'accepted {a} as ')
        assert (tmp_path/'learned'/'AGENTS.md').read_text() == 'Read sizes from ls.\n'
        assert run(f'/learned reject {b}') == f'rejected {b}' and run('/learned') == 'nothing is pending'
        assert 'nothing is pending' in run(f'/learned accept {b}')   # gone
        assert 'learned' in agent.commands() and '/learned' in HELP
    finally: tty.close()


def test_the_learned_command_without_a_config_folder():
    agent, _ = fake_agent()
    assert agent.command('/learned') == 'no config folder, so no learned folder'


def test_the_learned_compact_command_in_the_interface(tmp_path, monkeypatch):
    "`/learned compact` proposes a shorter AGENTS.md through Dhrona, and the accept-past-limit error points at it."
    import asyncio, subprocess
    import dhrona.improve
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import GUIDE, HELP, Ui
    f, b = tmp_path/'learned', '20261019-020202-bbbbbb'
    f.mkdir(); (f/'AGENTS.md').write_text('A rule a person wrote.\n')
    for c in (['init', '-q'], ['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-qm', 'by hand']):
        subprocess.run(['git', '-C', str(f), *c], check=True)
    _propose(f, {'AGENTS.md': 'A rule a person wrote.\n\n' + 'Read sizes with ls -l. ' * 50 + '\n'}, b)
    subprocess.run(['git', '-C', str(f), 'merge', '-q', '--ff-only', f'pending/{b}'], check=True)
    subprocess.run(['git', '-C', str(f), 'branch', '-D', f'pending/{b}'], check=True, capture_output=True)
    sent = []
    monkeypatch.setattr(dhrona.improve, '_editor', lambda *a, **k: lambda prompt: sent.append(prompt) or '[kept 1]\n\nRead sizes with ls -l.')
    agent, _ = fake_agent(cfg=tmp_path)
    tty = EmuTty(100, 30); comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    ui = Ui(comp, agent)
    def run(line):
        ui.buf.insert(line); ui.submit()
        return [blk.source for blk in ui.comp.blocks.values() if blk.tag == 'note'][-1]
    try:
        out = run('/learned compact')
        assert out.startswith('compaction pending as ') and '→' in out and sent, out
        id = out.split()[3].rstrip(':')
        assert id in run('/learned') and 'Compact learned AGENTS.md' in run('/learned')
        assert '+Read sizes with ls -l.' in run(f'/learned diff {id}')
        assert 'already pending' in run('/learned compact')
        assert run(f'/learned accept {id}').startswith(f'accepted {id} as ')
        assert (f/'AGENTS.md').read_text() == 'A rule a person wrote.\n\nRead sizes with ls -l.\n'
        assert '/learned compact' in HELP and '/learned compact' in GUIDE and "say /learned, /learned compact" in run('/learned nope')
    finally: tty.close()


def test_accept_past_the_limit_points_at_compact(tmp_path):
    from ramabana.learned import accept
    a = '20261019-010101-aaaaaa'
    _propose(tmp_path/'learned', {'AGENTS.md': 'x' * 2001}, a)
    assert f'run `/learned compact {a}`' in accept(tmp_path/'learned', a)['error']


def test_a_candidate_refused_for_size_is_folded_into_a_compaction(tmp_path, monkeypatch):
    "The refusal names `/learned compact ID`; that compaction carries the candidate, and accepting it moves the rest onto the new HEAD."
    import asyncio, subprocess
    import dhrona.improve
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    f, big, skill = tmp_path/'learned', '20261019-020202-bbbbbb', '20261019-030303-cccccc'
    f.mkdir(); (f/'AGENTS.md').write_text('A rule a person wrote.\n')
    for c in (['init', '-q'], ['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@x', 'commit', '-qm', 'by hand']):
        subprocess.run(['git', '-C', str(f), *c], check=True)
    _propose(f, {'AGENTS.md': 'A rule a person wrote.\n\n' + 'Run pytest -q before a commit. ' * 70 + '\n'}, big)
    _propose(f, {'skills/rg/SKILL.md': '---\nname: rg\ndescription: x\n---\nuse rg\n'}, skill)
    monkeypatch.setattr(dhrona.improve, '_editor', lambda *a, **k: lambda prompt: '[kept 1]\n\nRun pytest -q before a commit.')
    agent, _ = fake_agent(cfg=tmp_path)
    tty = EmuTty(100, 30); comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    ui = Ui(comp, agent)
    def run(line):
        ui.buf.insert(line); ui.submit()
        return [blk.source for blk in ui.comp.blocks.values() if blk.tag == 'note'][-1]
    try:
        assert f'run `/learned compact {big}`' in run(f'/learned accept {big}')
        out = run(f'/learned compact {big}')
        assert out.startswith('compaction pending as '), out
        id = out.split()[3].rstrip(':')
        out = run(f'/learned accept {id}')
        assert out.startswith(f'accepted {id} as ') and f'moved {skill} onto it' in out, out
        assert (f/'AGENTS.md').read_text() == 'A rule a person wrote.\n\nRun pytest -q before a commit.\n'
        assert big not in run('/learned') and skill in run('/learned')   # the folded candidate went with the compaction
    finally: tty.close()
