"Plan mode, as in Claude Code: mid-session, the model reads and proposes, and nothing it can call acts."
import pytest
from ramabana.testing import fake_agent


def test_plan_mode_withholds_acting_tools_rebriefs_the_live_model_and_gives_them_back():
    a, be = fake_agent()
    spec = a.routing.spec('turn')
    a._backends[(spec.backend, spec.model_id)] = be   # a model already running, which must be re-briefed in place
    names = lambda: {t.__name__ for t in a.tools}
    assert {'replace_text', 'run_shell', 'view_file'} <= names()
    assert a.set_plan_mode(True) is True and a.plan_mode
    assert 'view_file' in names() and not ({'replace_text', 'run_shell', 'create_file'} & names())
    assert 'Plan mode' in be.sp and 'replace_text' not in {t.__name__ for t in be.tools}
    assert 'plan mode' in a.command('/planmode').lower()
    a.set_plan_mode(False)
    assert 'replace_text' in names() and 'Plan mode' not in be.sp
    assert 'replace_text' in {t.__name__ for t in be.tools}


def test_plan_mode_does_not_switch_under_a_running_turn():
    a, _ = fake_agent()
    a._new_run('q').start()
    assert a.busy
    with pytest.raises(RuntimeError): a.set_plan_mode(True)
    assert not a.plan_mode
