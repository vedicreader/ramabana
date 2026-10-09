"""The seams a non-terminal frontend needs: approval decisions, mode switches, command expansion, watch and background callbacks, the verify text."""
from ramabana.testing import fake_agent


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
