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
