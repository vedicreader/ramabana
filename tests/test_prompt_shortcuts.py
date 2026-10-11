from ramabana.runtime import prompt_notices, Q_NOTICE


def test_bare_shortcuts_do_not_reinterpret_normal_punctuation():
    for prompt, meaning in (('.', 'continue'), (';', 'simpler'), (',', 'questions')):
        notices = prompt_notices(' ' + prompt + ' ')
        assert len(notices) == 1 and meaning in notices[0].lower()
    assert prompt_notices('a, b; c.') == []
    assert Q_NOTICE in prompt_notices('what changed?')
