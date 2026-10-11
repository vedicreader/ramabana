from types import SimpleNamespace
from ramabana.core import budget_for


def test_automatic_result_budget_scales_but_explicit_caps_win():
    small = SimpleNamespace(ctx=8192)
    large = SimpleNamespace(ctx=200000)
    assert budget_for(large, None).tool_max == 32000
    assert 1500 <= budget_for(small, None).tool_max < 6000
    assert budget_for(None, None).tool_max == 6000
    assert budget_for(large, 4000).tool_max == 4000
