"""The headless server: sessions, a prompt streamed as SSE events, approvals answered over HTTP,
and an OpenAPI document built from the same routes the app serves.
"""
import asyncio
import json
import threading
import time

from starlette.testclient import TestClient

from ramabana.agent import Approvals
from ramabana.serve import _events, app
from ramabana.testing import fake_agent


def _sse_events(text):
    "`[(event, data)]` parsed from a raw SSE response body."
    out = []
    for block in text.replace('\r\n', '\n').strip().split('\n\n'):
        kind = data = None
        for line in block.splitlines():
            if line.startswith('event:'): kind = line[len('event:'):].strip()
            elif line.startswith('data:'): data = line[len('data:'):].strip()
        if kind: out.append((kind, json.loads(data) if data else None))
    return out


def test_session_lifecycle_create_list_and_close(tmp_path):
    a = app([str(tmp_path)])
    c = TestClient(a)
    sid = c.post('/sessions', json={}).json()['session_id']
    try:
        assert sid in c.get('/sessions').json()['sessions']
        assert c.get('/sessions/nosuch/plan').status_code == 404
        plan = c.get(f'/sessions/{sid}/plan').json()
        assert plan['title'] == '' and plan['todos'] == []
    finally:
        assert c.delete(f'/sessions/{sid}').json() == {'closed': True}
    assert c.delete(f'/sessions/{sid}').status_code == 404


def test_prompt_streams_chunks_and_ends_with_the_reply(tmp_path):
    a = app([str(tmp_path)])
    c = TestClient(a)
    agent, _ = fake_agent(replies=['hello world'])
    a.state.sessions.agents[agent.session_id] = agent

    r = c.post(f'/sessions/{agent.session_id}/prompt', json={'prompt': 'hi'})
    events = _sse_events(r.text)
    kinds = [k for k, _ in events]
    assert kinds[-1] == 'done' and any(k == 'chunk' for k in kinds)
    chunks = ''.join(d['text'] for k, d in events if k == 'chunk')
    assert chunks.strip() == 'hello world'
    assert events[-1][1]['reply'].strip() == 'hello world'

    assert c.post('/sessions/nosuch/prompt', json={'prompt': 'hi'}).status_code == 404
    assert c.post(f'/sessions/{agent.session_id}/prompt', json={'prompt': ''}).status_code == 400


def test_a_pending_approval_answers_over_http_and_reaches_the_waiting_ask(tmp_path):
    a = app([str(tmp_path)])
    c = TestClient(a)
    agent, _ = fake_agent(replies=['ok'])
    agent.approvals = Approvals(tools={'edit_file'}, timeout=5)
    unhook = agent.approvals.listen()
    a.state.sessions.agents[agent.session_id] = agent

    result = {}
    def gate():
        result['ask'] = agent.approvals.gate({'function': {'name': 'edit_file', 'arguments': {'path': 'a.py'}}})
    t = threading.Thread(target=gate, daemon=True)
    t.start()
    for _ in range(100):
        if agent.approvals.pending is not None: break
        time.sleep(0.01)
    ask = agent.approvals.pending
    assert ask is not None
    r = c.post(f'/sessions/{agent.session_id}/approval', json={'id': ask.id, 'ok': True, 'note': 'go ahead'})
    assert r.json()['answer'] is True
    t.join(timeout=5)
    assert result['ask'].pending is False and result['ask'].note == 'go ahead'
    unhook()

    assert c.post(f'/sessions/{agent.session_id}/approval',
                  json={'id': 'nosuch', 'ok': True}).status_code == 409


def test_disconnecting_mid_stream_cancels_the_turn_instead_of_leaving_it_running():
    "A client that walks away must not leave the turn (and its tokens) running unattended."
    agent, _ = fake_agent()
    release = threading.Event()
    def slow_stream(prompt, **kw):
        yield 'partial '
        release.wait(5)   # held "in flight" until the test lets it go, after asserting cancel fired
    agent.stream = slow_stream
    cancelled = []
    agent.cancel = lambda: cancelled.append(True)

    async def go():
        gen = _events(agent, 'hi')
        first = await gen.__anext__()
        assert first['event'] == 'chunk'
        await gen.aclose()
        release.set()   # let the pump thread's now-orphaned `put('done', ...)` land while the loop still runs
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert cancelled == [True]


def test_openapi_document_lists_every_route(tmp_path):
    a = app([str(tmp_path)])
    doc = TestClient(a).get('/openapi.json').json()
    assert doc['paths']['/sessions']['get']['operationId'] == '_list_sessions'
    assert 'post' in doc['paths']['/sessions/{sid}/prompt']
