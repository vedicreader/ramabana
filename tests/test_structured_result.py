"A turn can hand back a typed value: `ask(schema=)` adds a `submit_result` tool for the turn and returns a `TurnResult`."
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from ramabana import agent
from ramabana.testing import FakeBackend, fake_agent


class Part(BaseModel):
    title: str
    start: int

class Outline(BaseModel):
    work: str
    parts: list[Part]


class Submitting(FakeBackend):
    "A model that calls `submit_result` with each payload in turn, the way a real one calls a tool."
    def __init__(self, owner, payloads, **kw):
        super().__init__(**kw)
        self.owner, self.payloads, self.said = owner, list(payloads), []
    def _send(self, msg, **kw):
        self.sent.append(msg)
        tool = next((t for t in self.owner.tools if t.__name__ == 'submit_result'), None)
        while tool is not None and self.payloads: self.said.append(tool(result=self.payloads.pop(0)))
        return 'done'

def _agent(payloads, tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    be = Submitting(a, payloads)
    a._be = a._be_or_none = lambda job='turn': be
    return a, be


def test_a_turn_hands_back_a_typed_result_and_a_bad_one_is_sent_back_to_fix(tmp_path):
    good = {'work': 'Isha', 'parts': [{'title': 'invocation', 'start': 1}]}
    a, be = _agent([{'work': 'Isha', 'parts': [{'title': 'x', 'start': 'one'}]}, good], tmp_path)
    r = a.ask('outline the Isha Upanishad', schema=Outline)
    assert isinstance(r, agent.TurnResult) and r.state == 'complete' and r.reply == 'done'
    assert isinstance(r.result, Outline) and r.result.parts[0].start == 1
    assert 'does not match' in be.said[0] and be.said[1] == 'result received', be.said
    assert r.session == a.session_id and r.turn_id == a.current_turn_id and 'submit_result' in be.sent[0]
    assert 'submit_result' not in {t.__name__ for t in a.tools}, 'the tool lasts for the call only'


@dataclass
class Verdict:
    lawful: bool
    reason: str

def test_a_dataclass_or_a_json_schema_works_too(tmp_path):
    a, _ = _agent([{'lawful': True, 'reason': 'public domain'}], tmp_path)
    assert a.ask('is it lawful?', schema=Verdict).result == Verdict(True, 'public domain')
    schema = {'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n']}
    a, be = _agent([{'n': 'three'}, {'n': 3}], tmp_path)
    assert a.ask('how many?', schema=schema).result == {'n': 3} and 'does not match' in be.said[0]


def test_strict_raises_for_a_missing_result_after_asking_once_more_and_for_a_failed_turn(tmp_path):
    a, be = _agent([], tmp_path)
    with pytest.raises(agent.ResultMissing) as e: a.ask('outline it', schema=Outline, strict=True)
    assert len(be.sent) == 2 and 'submit_result' in be.sent[1], 'asked once more, then given up'
    assert e.value.result.state == 'complete' and e.value.result.result is None
    assert a.ask('outline it', schema=Outline).result is None, 'not strict: no result, no raise'
    a, _ = fake_agent(cfg=tmp_path)
    a.start = lambda: None
    assert a.ask('hello', result=True).state == 'failed'
    with pytest.raises(agent.TurnFailed): a.ask('hello', strict=True)
    assert isinstance(a.ask('hello'), str), 'plain ask is unchanged'


def test_a_list_result_and_a_prompt_of_parts(tmp_path):
    a, be = _agent([[1, 2, 3]], tmp_path)
    r = a.ask(['look at this', 'how many?'], schema=list[int])
    assert r.result == [1, 2, 3] and 'submit_result' in str(be.sent[0])
