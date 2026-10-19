"""The window guard: a turn that would overflow compacts or trims first, and one that still cannot fit says so plainly.

The fault this pins: a hosted chat's `token_count` is the window its last step reported, and a history rewrite
never changed it. So after compaction `fits` still saw the old count, raised, and every retry compacted again
and raised again. A resumed conversation had the opposite blind spot: no step had reported yet, so it counted 0.
"""
import json
from rishi.remote import RemoteChat
from urai import Resp
from ramabana.agent import Agent, prompt_text, turn_prompt
from ramabana.core import ModelSpec
from ramabana.runtime import EST_MARGIN, IMG_TOKENS, TRIMMED, RishiBackend, threshold, trim_hist, use_chat
from ramabana.testing import MemHost

CTX = 8_000
SPEC = ModelSpec('hosted', 'remote', 'gpt-5.1', ctx=CTX)
PNG = b'\x89PNG\r\n\x1a\n' + bytes(4000)


class Reported(RemoteChat):
    "A hosted chat with no wire: each step reports the whole window, as a provider does, and records what it was sent."
    sent = []
    def _load(self): return sum(len(json.dumps(m.get('content'), default=str)) for m in self.hist) // 3 + len(self.sp or '') // 3
    def _model_step(self, **kw):
        n = self._load(); Reported.sent.append(n)
        return Resp({'role': 'assistant', 'content': 'ok', 'usage': {'prompt_tokens': n, 'completion_tokens': 1, 'total_tokens': n + 1}})
    def _oneshot(self, prompt, sp='', think=None, max_tokens=None): return 'the summary'


def _agent(tmp_path=None):
    "An `Agent` whose every job runs on one `RishiBackend` over `Reported`."
    a = Agent(MemHost({'/proj/a.py': 'a = 1\n'}), extensions=False, profile='full', cfg=tmp_path)
    be = RishiBackend(SPEC, sp='brief', tools=[])
    a.routing.turn, a.routing.policy = SPEC.name, {}
    a.routing._cache[SPEC.name] = SPEC
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


def _big(n, size=3000): return [{'role': r, 'content': f'{r} {i} ' + 'x' * size} for i in range(n) for r in ('user', 'assistant')]


def _chat(mid, **kw): return Reported(mid, **{k: v for k, v in kw.items() if k in ('sp', 'tools', 'approve', 'ctx_limit')})


def test_compaction_clears_a_count_reported_before_it():
    "The wedge: a last step past the window, then compaction. The next turn must go out, not raise."
    a, be = _agent()
    with use_chat(_chat):
        be.start()
        be.chat.hist[:] = be.chat.mk_msgs([m['content'] for m in _big(6)])
        be.chat._ctx_tokens = CTX + 300   # what the provider said the last step held
        out = a.ask('next')
        assert out == 'ok', out
        assert a.compactor.count == 1 and be.used_tokens < CTX
        again = a.ask('and again')
        assert again == 'ok' and a.compactor.count == 1   # one compaction, not one per retry


def test_a_resumed_conversation_is_counted_before_it_is_sent():
    "No step has reported for a resumed conversation; the guard estimates it rather than counting 0."
    a, be = _agent()
    Reported.sent.clear()
    with use_chat(_chat):
        be.resume_hist(_big(8))
        be.start()
        assert be.used_tokens >= be.window_tokens() > CTX
        assert a.ask('carry on') == 'ok'
        assert a.compactor.count == 1 and max(Reported.sent) <= CTX


def test_fit_at_the_boundary():
    "Just under the line fits, one token over does not; the pending message carries `EST_MARGIN`."
    be = RishiBackend(SPEC)
    reserve = min(1024, CTX // 4)
    pend = -(-be.pending_tokens('hello') * EST_MARGIN // 1)
    be._used = CTX - reserve - int(pend)
    assert be.projected_tokens('hello') == CTX - reserve and be.fits('hello')
    be._used += 1
    assert not be.fits('hello')


def test_pictures_are_charged_at_img_tokens_and_trimmed_before_text():
    be = RishiBackend(SPEC)
    assert be.pending_tokens([PNG, 'what is this?']) == be.pending_tokens('what is this?') + IMG_TOKENS
    pic = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'A' * 50_000}}
    hist = [{'role': 'user', 'content': [pic, {'type': 'text', 'text': 'look'}]},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'f', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r' * 20_000},
            {'role': 'user', 'content': [pic, {'type': 'text', 'text': 'and this'}]},
            {'role': 'assistant', 'content': 'seen'}]
    freed = trim_hist(hist, 100)
    assert hist[2]['content'] == TRIMMED and freed > 100       # a tool result goes first
    assert isinstance(hist[0]['content'], list) and any(p.get('type') == 'image_url' for p in hist[0]['content'])
    trim_hist(hist, 10**6)
    assert not any(isinstance(p, dict) and p.get('type') == 'image_url' for p in hist[0]['content'])
    assert any(p.get('type') == 'image_url' for p in hist[3]['content'])   # the newest messages stay whole


def test_a_message_that_cannot_fit_says_so_without_a_raw_error():
    a, be = _agent()
    with use_chat(_chat):
        out = a.ask('y' * (CTX * 4))
    assert 'ValueError' not in out and 'does not fit hosted' in out and f'{CTX:,}-token window' in out
    assert f'--resume {a.session_id}' in out


def test_a_prompt_with_a_picture_is_logged_as_text(tmp_path):
    "The log once kept the repr of the picture's bytes, and a resume replayed it as hundreds of thousands of tokens."
    assert prompt_text([PNG, '<user-request>\nfix it\n</user-request>']) == '[image]\n<user-request>\nfix it\n</user-request>'
    legacy = {'prompt': str([PNG, '<user-request>\nfix it\n</user-request>'])}
    assert turn_prompt(legacy) == '[image]\n<user-request>\nfix it\n</user-request>'
    assert turn_prompt({'prompt': "[b'\\x89PNG broken"}).startswith('[image]')
    a, be = _agent(tmp_path)
    with use_chat(_chat):
        a.ask([PNG, 'what is this?'])
    row = json.loads((tmp_path/'agent-history.jsonl').read_text().splitlines()[-1])
    assert row['prompt'] == '[image]\nwhat is this?'


def test_a_legacy_row_resumes_small(tmp_path):
    a, be = _agent(tmp_path)
    a.history = [{'at': 0, 'session': 's1', 'state': 'interrupted', 'model': '', 'activity': [],
                  'prompt': str([bytes(300_000), '<user-request>\nfix the pane\n</user-request>']), 'reply': ''}]
    a.resume_session('s1')
    assert sum(len(str(m['content'])) for m in be._resume_hist) < 1000
