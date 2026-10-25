"A call whose arguments do not fit the tool's signature comes back as an `ERROR:` result the model can act on, never as a raised `TypeError`."
from ramabana.testing import fake_agent
from ramabana.tools import failed


def test_a_call_missing_a_required_argument_names_the_tool_and_the_argument():
    a, _ = fake_agent()
    out = {t.__name__: t for t in a.tools}['view_file']()
    assert failed(out), out
    assert 'view_file' in out and "'path'" in out, out
    assert 'start' in out, 'the expected parameters are listed so the model can retry'


def test_a_call_with_an_unknown_argument_is_refused_and_names_it():
    a, _ = fake_agent()
    out = {t.__name__: t for t in a.tools}['grep'](pattern='x', patern='y')
    assert failed(out), out
    assert 'grep' in out and "'patern'" in out, out
