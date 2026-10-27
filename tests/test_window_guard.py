"""The window guard: a turn that would overflow compacts or trims first, and one that still cannot fit says so plainly.

The fault this pins: a hosted chat's `token_count` is the window its last step reported, and a history rewrite
never changed it. So after compaction `fits` still saw the old count, raised, and every retry compacted again
and raised again. A resumed conversation had the opposite blind spot: no step had reported yet, so it counted 0.
"""
import json, re, pytest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ramabana.runtime as runtime
from rishi.remote import RemoteChat
from urai import Resp
from ramabana.agent import FRESH_HINT, Agent, prompt_text, turn_prompt
from ramabana.cli import CLI_FRESH
from ramabana.core import ModelSpec
from ramabana.runtime import EST_MARGIN, IMG_TOKENS, TRIMMED, RishiBackend, fit_content, threshold, trim_hist, use_chat
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


@pytest.mark.parametrize('ctx,cap', [(16384, 4096), (32768, 8192), (200000, 8192), (2048, 1024)])
def test_oneshot_output_scales_with_the_window(ctx, cap):
    assert runtime.oneshot_tokens(ctx) == cap


@pytest.mark.parametrize('rt,engine', [('remote', False), ('mlx', False), ('mlx', True)])
@pytest.mark.parametrize('ctx,requested,cap', [(200000, None, 8192), (16384, None, 4096), (16384, 123, 123)])
def test_oneshot_sends_the_window_cap_unless_the_caller_overrides_it(monkeypatch, rt, engine, ctx, requested, cap):
    sent, configured = [], []
    class Recording:
        def __init__(self, *a, **kw):
            self.hist = []
            if 'max_output_tokens' in kw: configured.append(kw['max_output_tokens'])
        def oneshot(self, prompt, sp, **kw): sent.append(kw['max_tokens']); return 'ok'
        def mk_msg(self, prompt): return {'role': 'user', 'content': prompt}
        def _model_step(self, **kw): sent.append(kw['max_output_tokens']); return Resp({'role': 'assistant', 'content': 'ok'})
    monkeypatch.setattr('rishi.Chat', Recording)
    be = RishiBackend(ModelSpec('recording', rt, 'recording/model', ctx=ctx))
    be.chat = Recording()
    if engine: be.chat.engine = object()
    assert be._oneshot('question', 'brief', requested) == 'ok'
    assert sent == [cap]
    if engine:
        assert configured == [runtime.oneshot_tokens(ctx)]
        assert be._oneshot('another question', 'brief', 321) == 'ok'
        assert sent == [cap, 321]


@pytest.mark.parametrize('ctx,requested,cap', [(200000, None, 8192), (16384, None, 4096), (16384, 123, 123)])
def test_oneshot_prompt_room_reserves_the_same_output_cap(ctx, requested, cap):
    be = RishiBackend(replace(SPEC, ctx=ctx))
    be.chat = SimpleNamespace(count_tokens=len)
    sp = 'brief'
    room = ctx - len(sp) - cap - runtime.ONESHOT_HEADROOM
    prompt = 'x' * room
    assert be._fit_oneshot(prompt, sp, requested) == prompt
    cut = be._fit_oneshot(prompt + 'tail', sp, requested)
    assert cut.startswith(runtime.ONESHOT_CUT) and cut.endswith('tail') and len(cut) <= room


@pytest.mark.parametrize('ctx,cap', [(200000, 4096), (8192, 2048)])
def test_compaction_summary_output_scales_with_the_window(tmp_path, monkeypatch, ctx, cap):
    sent = []
    def summary(self, prompt, sp='', think=None, max_tokens=None): sent.append(max_tokens); return 'the summary'
    monkeypatch.setattr(Reported, '_oneshot', summary)
    a, be = _agent(tmp_path)
    be.spec = replace(SPEC, ctx=ctx)
    with use_chat(_chat):
        be.start()
        be.chat.hist[:] = be.chat.mk_msgs([m['content'] for m in _big(6)])
        assert a.compact() == 'the summary'
    assert sent and set(sent) == {cap}
    assert ctx - threshold(ctx) >= cap


def test_compactor_default_budget_leaves_room_for_a_4096_token_summary(tmp_path, monkeypatch):
    budgets = []
    def fold(msgs, summariser, extra, budget, count): budgets.append(budget); return 'the summary'
    monkeypatch.setattr(runtime, 'fold_summary', fold)
    a, be = _agent(tmp_path)
    with use_chat(_chat):
        be.start()
        be.chat.hist[:] = be.chat.mk_msgs([m['content'] for m in _big(6)])
        assert a.compactor.compact(be, lambda *a: 'the summary', summary_ctx=16384, summary_count=len) == 'the summary'
    assert budgets == [16384 - 4096 - len(runtime.SUMMARISE_SP) - 64]


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


def test_a_briefing_too_large_for_the_window_says_so_without_a_raw_error():
    "`ContextFull` is left for the one case nothing can cut: the briefing and tools alone overflow. Its advice suits the host."
    a, be = _agent()
    be.sp = 'brief ' * CTX
    with use_chat(_chat):
        out = a.ask('hi')
    assert 'ValueError' not in out
    assert FRESH_HINT in out and '--resume' not in out and 'Quit' not in out
    a.fresh_hint = CLI_FRESH
    with use_chat(_chat):
        out = a.ask('hi')
    assert f'`ramabana --resume {a.session_id}`' in out


def _sent_user(be): return next(m for m in reversed(be.chat.hist) if m['role'] == 'user')


def _text(m): return m['content'] if isinstance(m['content'], str) else ''.join(p.get('text', '') for p in m['content'] if p.get('type') == 'text')


def test_a_huge_paste_goes_out_as_an_excerpt_and_is_kept_whole(tmp_path):
    a, be = _agent(tmp_path)
    paste = 'START ' + ''.join(f'line {i}\n' for i in range(20_000)) + ' END'
    Reported.sent.clear()
    with use_chat(_chat):
        assert a.ask(paste) == 'ok'
    assert max(Reported.sent) <= CTX and a.compactor.count == 0, 'a short conversation is not compacted for a paste'
    sent = _text(_sent_user(be))
    assert sent.startswith('START') and 'END' in sent
    path = Path(re.search(r'full text at (\S+?\.txt)', sent).group(1))
    assert path.read_text() == paste and path.parent == a.runs_dir/'full' and path.stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path/'agent-history.jsonl').read_text().splitlines()[-1])['prompt'] == paste, 'the log keeps the whole prompt'


def test_many_pictures_keep_the_newest_that_fit_and_name_the_rest(tmp_path):
    a, be = _agent(tmp_path)
    pics = [PNG[:-1] + bytes([i]) for i in range(10)]
    with use_chat(_chat):
        assert a.ask([*pics, 'what changed?']) == 'ok'
    m = _sent_user(be)
    kept = [p for p in m['content'] if p.get('type') == 'image_url']
    assert 0 < len(kept) < 10 and be.used_tokens <= CTX
    note = _text(m)
    assert 'what changed?' in note
    saved = re.findall(r'(/\S+?\.png)', note)
    assert [Path(p).read_bytes() for p in saved] == pics[:10 - len(kept)], 'the oldest pictures are the ones saved'


def test_a_giant_tool_result_in_the_newest_exchange_is_cut_and_kept(tmp_path):
    a, be = _agent(tmp_path)
    big = 'r' * 60_000
    with use_chat(_chat):
        be.resume_hist([{'role': 'user', 'content': 'read it'},
                        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'view_file', 'arguments': '{}'}}]},
                        {'role': 'tool', 'tool_call_id': 'c1', 'content': big}])
        assert a.ask('next') == 'ok'
    tool = next(m for m in be.chat.hist if m['role'] == 'tool')
    assert 'full text at' in tool['content'] and len(tool['content']) < len(big)
    assert Path(re.search(r'full text at (\S+?\.txt)', tool['content']).group(1)).read_text() == big


def test_compaction_over_a_huge_history_folds_it_in_runs_that_each_fit():
    asked = []
    class Folding(Reported):
        def _oneshot(self, prompt, sp='', think=None, max_tokens=None): asked.append(len(prompt) // 3); return f'summary {len(asked)}'
    a, be = _agent()
    with use_chat(lambda mid, **kw: Folding(mid, **{k: v for k, v in kw.items() if k in ('sp', 'tools', 'approve', 'ctx_limit')})):
        be.start()
        be.chat.hist[:] = be.chat.mk_msgs([m['content'] for m in _big(60)])
        assert a.compact() == f'summary {len(asked)}'
    assert len(asked) > 2 and max(asked) < CTX and a.compactor.count == 1


def test_an_excerpt_keeps_the_reminders_at_its_end_and_a_trimmed_result_is_saved_once():
    saved = []
    def save(data, suffix): saved.append(data); return Path(f'/tmp/x{len(saved)}{suffix}')
    tail = '\n\n<tool-plan route="explicit">use grep</tool-plan>'
    out = fit_content('a' * 20_000 + tail, 300, save, tail=len(tail))
    assert out.endswith(tail) and 'characters omitted; full text at /tmp/x1.txt' in out and saved == [b'a' * 20_000]
    hist = [{'role': 'tool', 'tool_call_id': 'c', 'content': 'r' * 5000}, {'role': 'user', 'content': 'u'}, {'role': 'assistant', 'content': 'a'}]
    trim_hist(hist, 10**6, save=save); trim_hist(hist, 10**6, save=save)
    assert len(saved) == 2 and hist[0]['content'].startswith(TRIMMED[:-1]) and '/tmp/x2.txt' in hist[0]['content']


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


def test_a_resumed_conversation_not_yet_started_is_counted_too():
    "The first turn after `--resume` finds the chat unstarted; the guard counts what it will restore and starts it to cut."
    a, be = _agent()
    Reported.sent.clear()
    with use_chat(_chat):
        be.resume_hist(_big(8))
        assert be.chat is None and be.used_tokens > CTX
        assert a.ask('carry on') == 'ok'
    assert max(Reported.sent) <= CTX
