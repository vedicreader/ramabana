"`read_key`: one key from the key file, with the environment left as it was and no `!command` run."
import os

from ramabana.setup import read_key, save_key


def keys(tmp_path, text):
    p = tmp_path/'keys.env'
    p.write_text(text); p.chmod(0o600)
    return p


def test_the_environment_stays_the_same(tmp_path):
    p, before = keys(tmp_path, 'RB_TEST_A=one\nRB_TEST_B=two\n'), dict(os.environ)
    assert read_key('RB_TEST_A', p) == 'one'
    assert dict(os.environ) == before


def test_a_command_value_is_not_run(tmp_path):
    flag = tmp_path/'ran'
    p = keys(tmp_path, f'RB_TEST_CMD=!touch {flag}\n')
    assert read_key('RB_TEST_CMD', p) == '' and not flag.exists()


def test_quoted_and_saved_values(tmp_path):
    p = keys(tmp_path, "RB_TEST_Q='a b=c'\nRB_TEST_D=\"x\\\"y\"\n")
    assert read_key('RB_TEST_Q', p) == 'a b=c' and read_key('RB_TEST_D', p) == 'x"y'
    save_key('RB_TEST_BANG', '!not-a-command', p)
    os.environ.pop('RB_TEST_BANG', None)
    assert read_key('RB_TEST_BANG', p) == '!not-a-command', 'a typed key that starts with ! is text'


def test_a_missing_file_or_name_and_a_file_others_can_read(tmp_path):
    assert read_key('RB_TEST_A', tmp_path/'none.env') == ''
    p = keys(tmp_path, 'RB_TEST_A=one\n')
    assert read_key('RB_TEST_NONE', p) == ''
    p.chmod(0o644)
    assert read_key('RB_TEST_A', p) == ''
