from ramabana.runtime import prompt_notices, Q_NOTICE


def test_bare_shortcuts_do_not_reinterpret_normal_punctuation():
    for prompt in '.;,':
        assert len(prompt_notices(' ' + prompt + ' ')) == 1
    assert prompt_notices('a, b; c.') == []
    assert Q_NOTICE in prompt_notices('what changed?')
