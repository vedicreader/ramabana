"The terminal UI keeps drawing while a tool on another thread redirects `sys.stdout`."
import contextlib, io, os, sys

from ramabana.cli import AppTty


def test_a_frame_reaches_the_terminal_while_a_tool_redirects_stdout(monkeypatch):
    "shalya's in-process Python runs under `redirect_stdout`; the TUI then raised `UnsupportedOperation: fileno` in `Ui._act`."
    r, w = os.pipe()
    term = os.fdopen(w, 'w')
    monkeypatch.setattr(sys, '__stdout__', term)
    tty = AppTty.__new__(AppTty)
    tty.gone = tty.dropped = False
    with contextlib.redirect_stdout(io.StringIO()): tty.write('frame')
    term.close()
    assert os.read(r, 100) == b'frame' and not tty.gone
