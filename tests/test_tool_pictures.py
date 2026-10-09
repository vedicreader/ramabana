"A picture a tool returns reaches a model that can see it, draws inline, and stays out of checkpoints."
from base64 import b64decode

from shalya.core import Media
from urai import Chat, ChatOpts, Resp, ToolCall, ToolLoopMixin, is_media, mk_msg

from ramabana.testing import fake_agent

PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')


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


def test_checkpoints_and_branches_store_no_pictures(tmp_path):
    a, be = fake_agent(replies=['ok'], cfg=tmp_path)
    be.hist_[:] = [mk_msg(['shot', PNG])]
    a.ask('next')
    turn = list(a.checkpoints)[-1]
    cp = a.checkpoints[turn]
    assert 'base64' not in str(cp['before']) and 'base64' not in str(cp['after']) and '[image]' in str(cp['after'])
    a.undo_turn(turn)
    assert a._branch_hist and 'base64' not in str(a._branch_hist)


def test_attachments_load_without_the_terminal():
    """Leela imported its media helpers from `ramabana.cli`, which patches teleprint on import, so a teleprint release broke every Leela session."""
    import subprocess, sys
    code = ("import sys; from ramabana.tools import MEDIA, Attachment, media_note, media_parts; "
            "assert 'ramabana.cli' not in sys.modules and 'teleprint' not in sys.modules, sorted(m for m in sys.modules if 'tele' in m or m == 'ramabana.cli')")
    subprocess.run([sys.executable, '-c', code], check=True)
    from ramabana.cli import Attachment as A, media_note as n
    from ramabana.tools import Attachment, media_note
    assert A is Attachment and n is media_note, 'the terminal re-exports the same objects'
