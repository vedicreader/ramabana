"""The seams a non-terminal frontend needs: approval decisions, mode switches, command expansion, watch and background callbacks, the verify text."""
from ramabana.agent import APPROVE_MODES, Approvals
from ramabana.runtime import Run
from ramabana.testing import MemHost, fake_agent

from test_background import until
from test_briefing_and_rewind import PY, _turn_that_wrote


def test_decide_answers_what_needs_no_person_and_set_mode_settles_the_rest():
    ap = Approvals(tools={'edit_file', 'run_shell'}, mode='edits')
    assert ap.decide('edit_file', {'path': 'a.py'}).answer is True
    assert ap.decide('ls', {}).answer is True
    assert ap.decide('run_shell', {'command': 'ls'}) is None and len(ap.history) == 3
    assert ap.set_mode('yolo') == f"usage: /approve [{'|'.join(APPROVE_MODES)}]"
    assert ap.set_mode('edits') == 'approvals: edits'
    assert ap.set_mode('off') == 'approvals: edits -> off' and ap.decide('edit_file', {'path': 'a.py'}).answer is False


def test_expand_command_knows_skills_and_command_files(tmp_path):
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'hello.md').write_text('Say hello to $ARGUMENTS\n')
    a, _ = fake_agent(cfg=tmp_path)
    assert a.expand_command('/hello world') == 'Say hello to world'
    assert a.expand_command('/nosuch thing') is None
    if a.skills: assert a.expand_command(f'/{a.skills[0].name} fix it') == f'/{a.skills[0].name} fix it'


def test_a_command_file_fills_its_arguments_and_inlines_the_files_it_names(tmp_path):
    """`$1..$n` are the line's words (quoted words stay whole), `$ARGUMENTS` is the whole line, and an
    `@path` becomes the file where the host can read it; a path outside the open roots stays as written,
    since a command file is not a way round the sandbox."""
    from ramabana.testing import FullHost
    host = FullHost(files={'notes.md': 'remember the cedar\n'})
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'review.md').write_text('Review $1 for $2; all: $ARGUMENTS\n\n@notes.md and @/etc/hostname and @missing.md.\n')
    a, _ = fake_agent(host, cfg=tmp_path)
    out = a.expand_command('/review a.py "style and tests"')
    assert out.startswith('Review a.py for style and tests; all: a.py "style and tests"')
    assert '<file path="notes.md">\nremember the cedar\n</file>' in out
    assert '@/etc/hostname' in out and '@missing.md.' in out           # left as written: outside the roots, and absent
    (tmp_path/'commands'/'odd.md').write_text("Say $1 and $ARGUMENTS\n")
    assert a.expand_command("/odd it's fine") == "Say it's and it's fine"   # an unbalanced quote is still just words


def test_a_subtask_command_is_framed_for_a_sub_agent(tmp_path):
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'audit.md').write_text('---\nsubtask: true\n---\nAudit $ARGUMENTS\n')
    (tmp_path/'commands'/'bad.md').write_text('---\nsubtask: [unclosed\n---\nStill a command $ARGUMENTS\n')
    a, _ = fake_agent(cfg=tmp_path)
    out = a.expand_command('/audit the vault')
    assert out.endswith('Audit the vault') and 'delegate_async' in out.splitlines()[0]
    assert a.expand_command('/bad here') == 'Still a command here'      # malformed frontmatter is not a reason to refuse


def test_project_command_files_load_only_when_project_extensions_are_opted_in(tmp_path):
    "A repo's `.agents/commands/` runs what the repo says, so it needs the opt-in project hooks and extensions already need; `<cfg>/commands/` is the person's own."
    from ramabana.testing import FullHost
    host = FullHost()
    d = host.root/'.agents'/'commands'; d.mkdir(parents=True)
    (d/'ship.md').write_text('Ship $ARGUMENTS\n')
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'ship.md').write_text('Mine: $ARGUMENTS\n')
    a, _ = fake_agent(host, cfg=tmp_path)
    assert a.expand_command('/ship it') == 'Mine: it'
    b, _ = fake_agent(host, cfg=tmp_path, project_extensions=True)
    assert b.expand_command('/ship it') == 'Ship it', 'the project one wins once trusted'
    assert b.expand_command('/nosuch') is None


def test_watch_and_background_completion_reach_a_frontend_callback(tmp_path):
    a, _ = fake_agent(cfg=tmp_path)
    seen = []
    a.on_watch = lambda target, log: seen.append((target, log))
    assert a.watch('monitors') == 'watching monitors' and seen[0][0] == 'monitors' and seen[0][1].exists()
    a.on_background_done = lambda run, ans: seen.append(ans)
    a.background.start(lambda r: 'x is 42', Run('run_x', 'background', 'what is x', 'fake'))
    assert until(lambda: 'x is 42' in seen)


def test_the_verify_text_is_kept_and_streamed():
    host = MemHost({'/proj/a.py': 'def a(): pass\n', '/proj/pyproject.toml': PY}, commands={'pytest -q': (0, '3 passed')})
    a, _ = fake_agent(host, replies=['done'])
    _turn_that_wrote(a, host)
    a._finish('done')
    assert a.last_verify.startswith('verify (pytest -q)') and '3 passed' in a.last_verify
    prep = a._prepare
    def prep_and_write(p):
        out = prep(p)
        a.before['/proj/a.py'], host.files['/proj/a.py'] = host.files['/proj/a.py'], 'def a(): return 2\n'
        return out
    a._prepare = prep_and_write
    out = ''.join(a.stream('again'))
    assert 'done' in out and 'verify (pytest -q)' in out
    a._finish('quiet')
    assert a.last_verify == ''


def test_argument_substitution_is_one_pass_and_command_names_stay_in_their_folder(tmp_path):
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'many.md').write_text('tenth=$10 first=$1 all=$ARGUMENTS\n')
    (tmp_path/'commands'/'evil.md').write_text('never\n')
    a, _ = fake_agent(cfg=tmp_path)
    out = a.expand_command('/many a b c d e f g h i j')
    assert out == 'tenth=j first=a all=a b c d e f g h i j'
    assert a.expand_command('/many "$1 costs $ARGUMENTS" x') == 'tenth=$10 first=$1 costs $ARGUMENTS all="$1 costs $ARGUMENTS" x'
    for bad in ('/../commands/evil x', '/commands/evil x', '/..%2Fevil', '/ x'):
        assert a.expand_command(bad) is None, bad
