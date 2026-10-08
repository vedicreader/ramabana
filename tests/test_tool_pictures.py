"A picture a tool returns reaches a model that can see it, draws inline, and stays out of checkpoints."
from base64 import b64decode

import pytest
from shalya.core import Media
from urai import Chat, ChatOpts, Resp, ToolCall, ToolLoopMixin, is_media, mk_msg

from ramabana.agent import PICTURE_RULE
from ramabana.core import ModelSpec
from ramabana.runtime import RishiBackend, use_chat
from ramabana.testing import FakeBackend, fake_agent
from ramabana.tools import _inboxed, keep_media

PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


class _Caps:
    def __init__(self, inp=('text',), known=True): self.inp, self.known = inp, known
    def accepts(self, kind): return kind in self.inp


@pytest.fixture
def caps(monkeypatch):
    "Pin what `spec_caps` answers, so no test depends on a model table."
    box = {}
    monkeypatch.setattr('ramabana.core._caps', lambda mid, rt: box.get('c'))
    return lambda c: box.__setitem__('c', c)


class _Script(ToolLoopMixin, Chat):
    "A urai tool loop whose replies are scripted."
    _runtime = 'tp-script'
    def __init__(self, model=None, *, script=(), tools=(), **kw):
        self.script = list(script)
        self._setup(model, ChatOpts.create(None, tools=tools))
        self._set_tools(self.tools)
    def _model_step(self, **kw): return Resp({'role': 'assistant', **self.script.pop(0)})


def _shot(path):
    def screenshot(page: str = '') -> str:
        "Take a screenshot."
        return Media(f'screenshot saved to {path}', [str(path)])
    return screenshot


def test_a_screenshot_reaches_the_model_and_draws_inline(tmp_path):
    "The recorded tool keeps its `.media`, the loop sends the picture, and the turn's media carries it."
    (p := tmp_path/'shot.png').write_bytes(PNG)
    a, _ = fake_agent()
    tool = a._record(_shot(p))
    c = _Script(script=[{'content': '', 'tool_calls': [dict(ToolCall('screenshot', {}))]}, {'content': 'I see it'}], tools=[tool])
    c('look')
    assert [m['role'] for m in c.hist] == ['user', 'assistant', 'tool', 'user', 'assistant']
    assert sum(is_media(x) for x in c.hist[3]['content']) == 1
    assert a.last_media == [{'mime': 'image/png', 'data': PNG}]


def test_an_after_tool_hook_rewriting_the_text_keeps_the_picture(tmp_path):
    a, _ = fake_agent()
    a.registry.on('after_tool', lambda ag, name, out: out.upper())
    out = a._record(_shot(tmp_path/'s.png'))()
    assert out.startswith('SCREENSHOT SAVED') and out.media == [str(tmp_path/'s.png')]


def test_a_steering_message_appended_to_a_result_keeps_the_picture():
    class R:
        key = 'k'
        def on_call(self): pass
        def drain_inbox(self): return ['stop soon']
    out = _inboxed(lambda: Media('saved /x.png', ['/x.png']), R())()
    assert 'stop soon' in out and out.media == ['/x.png']
    assert keep_media('plain', 'old') == 'plain' and not hasattr(keep_media('a', 'b'), 'media')


def test_a_failed_tool_draws_nothing(tmp_path):
    a, _ = fake_agent()
    a._record(lambda: Media('ERROR: no page', [str(tmp_path/'x.png')]))()
    assert a.last_media == []


class _Wire:
    "A stand-in rishi chat: `_media_ok` is what its transport carries."
    def __init__(self, model=None, _media_ok=True, **kw): self._media_ok, self.hist = _media_ok, []
    def close(self): pass


@pytest.mark.parametrize('inp,wire,want', [(('text', 'image'), True, True), (('text',), True, False), (('text', 'image'), False, False)])
def test_the_turn_chat_takes_pictures_only_when_model_and_transport_both_can(caps, inp, wire, want):
    caps(_Caps(inp))
    with use_chat(lambda *a, **kw: _Wire(_media_ok=wire)):
        b = RishiBackend(ModelSpec('m', 'remote', 'm', 8000))
        b.start()
        assert b.chat.media_in is want and b.takes_pictures is want
        sub = b.spawn(sp='sub'); sub.start()
        assert sub.chat.media_in is want, 'each sub-agent backend is gated the same way'


def test_a_checkpoint_holds_the_placeholder_not_base64():
    b = FakeBackend(); b.start()
    b.hist_[:] = [{'role': 'user', 'content': 'go'}, mk_msg(['The 1 picture(s) below are the results of `screenshot`.', PNG])]
    snap = b.snapshot_hist()
    assert snap[1]['content'].endswith('[image]') and 'base64' not in str(snap)
    assert isinstance(b.hist_[1]['content'], list), 'the live history keeps the picture'


def test_checkpoints_and_branches_store_no_pictures(tmp_path):
    a, be = fake_agent(replies=['ok'], cfg=tmp_path)
    be.hist_[:] = [mk_msg(['shot', PNG])]
    a.ask('next')
    turn = list(a.checkpoints)[-1]
    cp = a.checkpoints[turn]
    assert 'base64' not in str(cp['before']) and 'base64' not in str(cp['after']) and '[image]' in str(cp['after'])
    a.undo_turn(turn)
    assert a._branch_hist and 'base64' not in str(a._branch_hist)


def test_the_briefing_follows_whether_the_turn_model_sees_pictures(caps):
    from shalya.host import BrowserHost
    from ramabana.testing import MemHost
    class Browsing(MemHost, BrowserHost):
        def browse(self, url): return 'p1'
        def screenshot(self, page=''): return '/tmp/p1.png'
        def page_text(self, page=''): return ''
        def page_reload(self, page=''): return ''
        def page_click(self, page, x, y): return ''
        def page_type(self, page, text): return ''
        def page_eval(self, page, js): return ''
    for inp, rule in ((('text', 'image'), PICTURE_RULE[True]), (('text',), PICTURE_RULE[False])):
        caps(_Caps(inp))
        a, _ = fake_agent(Browsing({'/proj/a.py': 'x\n'}), optin=('browser',))
        sp = a.system_prompt()
        assert rule.split('\n')[0] in sp and PICTURE_RULE[not ('image' in inp)].split('\n')[0] not in sp


def test_attachments_load_without_the_terminal():
    """Leela imported its media helpers from `ramabana.cli`, which patches teleprint on import, so a teleprint release broke every Leela session."""
    import subprocess, sys
    code = ("import sys; from ramabana.tools import MEDIA, Attachment, media_note, media_parts; "
            "assert 'ramabana.cli' not in sys.modules and 'teleprint' not in sys.modules, sorted(m for m in sys.modules if 'tele' in m or m == 'ramabana.cli')")
    subprocess.run([sys.executable, '-c', code], check=True)
    from ramabana.cli import Attachment as A, media_note as n
    from ramabana.tools import Attachment, media_note
    assert A is Attachment and n is media_note, 'the terminal re-exports the same objects'
