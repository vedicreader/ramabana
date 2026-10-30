from types import SimpleNamespace

import pytest

from ramabana.core import ModelSpec
from ramabana.testing import fake_agent


def test_oneshot_prepares_each_route_from_the_original_text_and_never_retries_a_refusal():
    a, _ = fake_agent()
    sent = []
    first = SimpleNamespace(spec=ModelSpec('first', 'remote', 'openai/first'), note='')
    second = SimpleNamespace(spec=ModelSpec('second', 'litert', 'local/second'), note='')
    first.oneshot = lambda prompt, sp, *args, **kwargs: sent.append((first.spec.name, prompt, sp)) or ''
    second.oneshot = lambda prompt, sp, *args, **kwargs: sent.append((second.spec.name, prompt, sp)) or 'answer'
    routes = iter([first, second])
    a._be_or_none = lambda job: next(routes, None)

    def prepare(prompt, sp, backend):
        return f'{backend.spec.name}:{prompt}', f'{backend.spec.name}:{sp}'

    assert a.oneshot('question', 'instructions', prepare=prepare) == 'answer'
    assert sent == [('first', 'first:question', 'first:instructions'),
                    ('second', 'second:question', 'second:instructions')]

    sent.clear()
    a.routing.down.clear()
    routes = iter([first, second])

    def refuse(prompt, sp, backend):
        raise ValueError('outgoing text refused')

    with pytest.raises(ValueError, match='outgoing text refused'):
        a.oneshot('question', 'instructions', prepare=refuse)
    assert not sent and not a.routing.down


def test_the_outgoing_guard_stops_a_oneshot_before_anything_is_sent_when_detection_is_missing(monkeypatch):
    import ramabana.guard as guard
    monkeypatch.setattr(guard, 'pii_report', None)
    a, _ = fake_agent()
    sent = []
    hosted = SimpleNamespace(spec=ModelSpec('hosted', 'remote', 'openai/gpt-5.6'), note='',
                             oneshot=lambda *args, **kwargs: sent.append(args) or 'answer')
    a._be_or_none = lambda job: hosted
    with pytest.raises(guard.OutgoingRefused, match='PII detection is unavailable'):
        a.oneshot('hello', prepare=lambda prompt, sp, backend: (guard.outgoing(prompt, backend.spec, mode='redact'), sp))
    assert not sent and not a.routing.down
