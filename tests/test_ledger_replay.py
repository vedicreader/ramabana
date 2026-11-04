"""Replay of a real failure (session agent_20261104-091959-044593): one request, then hundreds of tool steps.

Compaction kept no messages three times, and every plan step showed done, the handout step too, though
nothing checked it. After a compaction the next context has to hold the request, the honest state of each
step, and the last steps of the turn."""
from dataclasses import replace
from ramabana.runtime import LAST_ASK, done_items
from ramabana.testing import fake_agent

ASK = 'Build Step 7: the handout HTML with an Answers panel and folder links. Then run the full suite and restart the server.'


def _turn(steps=230):
    "One user message, then `steps` tool calls with large results, the last a failing test run."
    hist = [{'role': 'user', 'content': ASK}]
    for i in range(steps):
        name, args, out = ('run_shell', {'command': 'pytest -q tests'}, 'exit 1\nFAILED tests/test_handout.py::test_answers') if i == steps - 1 else \
                          ('view_file', {'path': f'abhyasa/blocks/f{i}.py'}, 'line of code\n' * 300)
        hist += [{'role': 'assistant', 'content': f'Reading part {i} of the handout.', 'tool_calls': [{'id': f'c{i}', 'type': 'function', 'function': {'name': name, 'arguments': args}}]},
                 {'role': 'tool', 'tool_call_id': f'c{i}', 'name': name, 'content': out}]
    return hist


def test_after_compaction_the_next_context_has_the_request_the_honest_plan_and_the_tail(tmp_path):
    a, be = fake_agent(cfg=tmp_path, replies=['next'])
    a.plan.set('', ['Step 7: handout', 'Step 8: walk', 'nbdev-prepare and full suite green'])
    a.plan.update('Step 7', status='done')                       # what the session did: done, with nothing to show
    a.plan.update('Step 8', status='done', evidence='9c41e2d')
    a.plan.update('full suite', status='active')
    a.plan.ask(ASK, 'turn_000001')
    be.spec = replace(be.spec, ctx=200_000)   # the window of the model the session ran on
    be.start(); be.hist_ = _turn()
    tail = be.hist_[-2:]
    assert a.compact(), a.compactor.note
    assert 'into a digest' in a.compactor.note, 'no model is asked'
    head = be.hist_[0]['content']
    assert be.hist_[-2:] == tail and len(be.hist_) > 3, 'the tail stays: compaction does not keep 0 messages'
    assert f'[open] {ASK}' in head, "the user's request, word for word"
    assert LAST_ASK not in head and head.count(ASK) == 2, 'the request is in the ledger and on its digest line, and is not pinned a third time'
    assert 'Step 7: handout -- not checked' in head and 'Step 7' not in done_items(head), 'the unchecked step is not reported done'
    assert 'Step 8: walk -- evidence: 9c41e2d' in done_items(head)
    assert 'full suite green -- active' in head
    assert '▶ view_file abhyasa/blocks/f0.py · ok' in head and '» Reading part 0 of the handout.' in head, 'the old steps are one line each'
    assert 'line of code' not in head, 'tool output is not copied'
    assert 'Step 7: handout' in a.system_prompt() and 'no evidence' in a.system_prompt()
    a.ask('go on')
    assert be.hist_[0]['content'] == head and be.hist_[-1]['content'] == 'next', 'the next turn runs on the digest'


def test_a_handoff_starts_the_fresh_context_from_the_ledger_and_a_turn_records_its_files(tmp_path):
    a, be = fake_agent(cfg=tmp_path, replies=['wrote it'])
    a.ask(ASK)
    a.before['/proj/a.py'] = 'def a(): pass\n'   # what a write tool keeps before its first write of the turn
    a._finish('wrote it', ASK)
    assert a.plan.files == ['/proj/a.py'] and '- /proj/a.py' in a.plan.ledger()
    be.hist_ = _turn(20)
    a.handoff()
    assert 'handed off' in a.compactor.note and len(be.hist_) == 1, a.compactor.note
    head = be.hist_[0]['content']
    assert head.index('## Session ledger') < head.index('▶ view_file abhyasa/blocks/f0.py · ok') and f'[open] {ASK}' in head
