"Rules the project states in prose, enforced where a call is made: the refusal teaches mid-turn."
from ramabana.agent import mk_agent, mk_host, shell_denial
from ramabana.testing import MemHost, fake_agent
from ramabana.tools import failed
from shalya.tools import tools_for
import pytest

KEY = 'sk-test' + 'abcdefghijklmnopqrstuvwxyzabcd'   # key-shaped and made up
PAT = 'github_pat_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3'


def test_shell_guard_refuses_hidden_output_but_not_quoted_text_or_plain_redirects():
    for bad in ('pytest -q | tail -20', 'make 2>&1', 'ls -la | head', 'sh -c "pytest | tail"', 'make |& tail'):
        assert shell_denial(bad), bad
    for ok in ('pytest -q', 'echo "a | head"', "grep '2>&1' notes.txt", 'cmd > out.txt 2> err.txt',
               'git log | grep fix', 'tail -n 5 log.txt'):
        assert shell_denial(ok) == '', ok


def test_the_shell_refuses_what_prints_the_environment():
    for bad in ('env', 'printenv', 'printenv OPENAI_API_KEY', 'env | grep KEY', 'env -0', 'env -u TMUX', 'FOO=1 env', 'echo hi && env',
                'sh -c "printenv"', 'sudo env', 'echo $(printenv HOME)', 'set', 'export', 'export -p', 'declare -x', 'declare -p', 'declare -p HOME',
                'cat /proc/self/environ', 'strings /proc/1/environ', 'cat .env', 'less app/.env', 'head .env.local', 'tail -n 3 .env', 'grep KEY .env',
                'sudo -u root env', 'nice -n 5 printenv', 'timeout 5 env', 'xargs env', 'cat < .env', 'cat $HOME/.env',
                'env printenv', 'env FOO=1 cat .env', 'env sh -c printenv', 'timeout -k 5 10 env', 'xargs -n 1 printenv',
                'X=a/timeout printenv', 'time -v printenv', 'timeout --kill-after 5 10 env', 'xargs --max-args 1 printenv',
                'nice --adjustment 5 printenv', 'exec -a x printenv'):
        assert 'test -n "$NAME" && echo set' in shell_denial(bad), bad
    for ok in ('env -u TMUX pytest -q', 'env FOO=1 python -c pass', 'set -e', 'set -o pipefail', 'export FOO=1', 'declare -x FOO=1', 'echo "env"',
               'cat env.py', 'grep env README.md', 'cat .envrc', 'echo "cat .env"', 'test -n "$NAME" && echo set',
               'command -v env', 'cat .env.example', 'grep KEY .env.sample', 'declare --help', 'timeout 5 env -u X pytest', 'env --help',
               'cat docs/.env.md'):
        assert shell_denial(ok) == '', ok
    out = {t.__name__: t for t in fake_agent()[0].tools}['run_shell']('printenv')
    assert failed(out) and 'echo set' in out, out


def test_every_read_comes_back_with_keys_masked(tmp_path):
    (tmp_path/'conf.py').write_text(f'TOKEN = "{KEY}"\nGH = "{PAT}"\n')
    (tmp_path/'notes.txt').write_text(f'deploy key {KEY}\n')
    t = {f.__name__: f for f in tools_for(mk_host([str(tmp_path)], web=False, index=False))}
    outs = dict(view_file=t['view_file'](str(tmp_path/'conf.py')), run_shell=t['run_shell']('cat notes.txt', cwd=str(tmp_path)),
                run_python=t['run_python'](f'open({str(tmp_path/"notes.txt")!r}).read()'), grep=t['grep']('deploy key'))
    for name, o in outs.items(): assert KEY not in o and '[SECRET]' in o, (name, o)
    assert PAT not in outs['view_file'], 'a GitHub fine-grained token, which rahasya does not know, is masked too'


def test_a_write_never_puts_the_mask_over_a_real_key(tmp_path):
    (tmp_path/'conf.py').write_text(f'TOKEN = "{KEY}"\nDEBUG = False\n')
    (tmp_path/'notes.md').write_text('Keys come back as [SECRET].\n')
    a, _ = fake_agent(host=mk_host([str(tmp_path)], web=False, index=False))
    t = {f.__name__: f for f in a.tools}
    out = t['create_file'](str(tmp_path/'conf.py'), 'TOKEN = "[SECRET]"\nDEBUG = True\n')
    assert failed(out) and 'holds a key' in out and KEY in (tmp_path/'conf.py').read_text(), out
    t['replace_text'](str(tmp_path/'conf.py'), [{'oldText': 'DEBUG = False', 'newText': 'DEBUG = True'}])
    assert (tmp_path/'conf.py').read_text() == f'TOKEN = "{KEY}"\nDEBUG = True\n', 'an edit around the key goes through'
    t['replace_text'](str(tmp_path/'notes.md'), [{'oldText': 'as [SECRET].', 'newText': 'as [SECRET], always.'}])
    assert 'always' in (tmp_path/'notes.md').read_text(), 'a file that only names the mask can be edited'


def test_every_documented_key_shape_is_masked_and_an_unterminated_pem_quickly():
    import time
    from ramabana.agent import mask_secrets
    pem = '-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY-----'
    for k in ('sk_live_' + 'a1' * 12, 'rk_test_' + 'b2' * 12, 'hf_' + 'c' * 34, 'glpat-' + 'd' * 20, 'npm_' + 'e' * 36,
              'pypi-' + 'f' * 60, 'ASIA' + 'G' * 16, 'gho_' + 'h' * 36, pem, '-----BEGIN PRIVATE KEY-----\nMIIEcut',
              '-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOY\n-----END PGP PRIVATE KEY BLOCK-----'):
        got = mask_secrets(f'value: {k}\nnext')
        assert k not in got and '[SECRET]' in got, got
    start = time.time()
    mask_secrets('-----BEGIN PRIVATE KEY-----\nabc\n' * 8_000)
    assert time.time() - start < 1, 'one unterminated block masks to the end, so the scan stays linear'


def test_the_fallback_key_shapes_are_rahasyas():
    "Without the search extra there is no rahasya, so ramabana carries its `secret` shapes; this says when rahasya's change."
    PATTERNS = pytest.importorskip('rahasya.core').PATTERNS
    from ramabana.agent import RAHASYA_SECRETS
    assert PATTERNS['secret'][0] == rf'\b(?:{RAHASYA_SECRETS})\b'


def test_the_agent_tells_the_read_guard_which_model_reads(tmp_path):
    a, h = mk_agent([str(tmp_path)], approve='none', web=False, cfg=tmp_path/'cfg', extensions=False, subagents=False)
    assert h.model_local() == (a.model.local, a.model.name)
    from ramabana.runtime import Run, run_context
    with run_context(Run('run_x', 'child', 'q', 'litert/gemma')): assert h.model_local() == (True, 'litert/gemma'), 'a sub-agent reads with its own model'
    assert '[SECRET]' in a.system_prompt()


def test_a_write_to_a_generated_module_is_refused_and_names_its_notebook():
    gen = '# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_m.ipynb.\n\nx = 1\n'
    host = MemHost({'/proj/pkg/m.py': gen, '/proj/a.py': 'x = 1\n'})
    a, _ = fake_agent(host=host)
    tools = {t.__name__: t for t in a.tools}
    out = tools['replace_text']('/proj/pkg/m.py', [{'oldText': 'x = 1', 'newText': 'x = 2'}])
    assert 'nbs/01_m.ipynb' in out, out
    assert host.text_at('/proj/pkg/m.py') == gen
    tools['replace_text']('/proj/a.py', [{'oldText': 'x = 1', 'newText': 'x = 2'}])
    assert host.text_at('/proj/a.py') == 'x = 2\n'
    assert 'x = 1' in tools['view_file']('/proj/pkg/m.py'), 'reading a generated module is not editing it'


def test_a_rewritten_call_meets_the_guards_again():
    "An extension's `before_tool` rewrite ran unchecked, so it could add what the guard refuses."
    a, _ = fake_agent()
    a.registry.on('before_tool', lambda agent, name, args: dict(args, command=args['command'] + ' | head') if name == 'run_shell' else None)
    out = {t.__name__: t for t in a.tools}['run_shell']('echo hi')
    assert failed(out), out
