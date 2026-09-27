"""Skills as slash commands, `#note`, the always-allow key, and the one-shot JSON path."""
import asyncio, io, json, sys

import pytest
from teleprint.compositor import Compositor
from teleprint.keys import Key
from teleprint.testing import EmuTty

from ramabana.agent import Approvals, Ask
from ramabana.cli import Ui, ask_once, ask_pattern, headless_prompt
from ramabana.testing import fake_agent, MemHost
from ramabana.tools import WRITE_TOOLS


@pytest.fixture
def ui(tmp_path):
    tty = EmuTty(80, 24)
    comp = Compositor(tty)
    comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent(cfg=tmp_path)
    agent.approvals = Approvals(tools=WRITE_TOOLS, mode='ask')
    yield Ui(comp, agent)
    tty.close()


def _said(u): return ' '.join(u.transcript.block_text(b) for b in u.comp.blocks.values())

def _submit(u, line):
    u.buf.text = line
    out = u.submit()
    if asyncio.iscoroutine(out): out.close()
    return out


def test_a_skill_name_typed_as_a_command_becomes_a_prompt_with_the_skill_attached(ui):
    name = next(s.name for s in ui.agent.skills)
    assert asyncio.iscoroutine(_submit(ui, f'/{name} fix the loop')), 'a turn, not an error'
    assert ui._prompt == f'/{name} fix the loop', 'the line itself is the prompt: `prompt_directives` loads the skill from it'
    _submit(ui, '/nosuchthing at all')
    assert 'unknown command' in _said(ui)


def test_a_commands_file_is_a_prompt_with_its_arguments_filled_in(ui, tmp_path):
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'hello.md').write_text('Greet $ARGUMENTS warmly.\n')
    assert asyncio.iscoroutine(_submit(ui, '/hello the world'))
    assert ui._prompt == 'Greet the world warmly.'
    assert ui.agent.expand_command('/nosuch x') is None


def test_command_files_fill_positional_args_at_files_and_shell_and_honour_subtask(tmp_path):
    """A command body is more than `$ARGUMENTS`: `$1..$n` split like a shell line, `@path` inlines a
    file the host can read, and `!`cmd`` runs through the same approval gate a model's `run_shell`
    would. A project `.agents/commands/` file shadows the user-level `<cfg>/commands/` one, and a
    `subtask` command hands the work to a sub-agent instead of running in this turn.
    """
    host = MemHost({'/proj/notes.txt': 'keep calm'}, root=str(tmp_path), commands={'echo hi': (0, 'hi there')})
    a, _ = fake_agent(host=host, cfg=tmp_path)
    a.approvals = Approvals(tools={'run_shell'}, mode='auto')

    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'greet.md').write_text('Greet $1 about @/proj/notes.txt, then !`echo hi`.\n')
    got = a.expand_command('/greet world extra')
    assert 'Greet world about' in got and 'keep calm' in got and 'hi there' in got

    a.approvals = Approvals(tools={'run_shell'}, mode='off')
    refused = a.expand_command('/greet world extra')
    assert 'refused' in refused

    project = tmp_path/'.agents'/'commands'
    project.mkdir(parents=True)
    (project/'greet.md').write_text('---\ndescription: the project one wins\n---\nProject greets $ARGUMENTS.\n')
    assert a.expand_command('/greet world') == 'Project greets world.'

    (project/'delegated.md').write_text('---\nsubtask: true\n---\nInvestigate $ARGUMENTS.\n')
    out = a.expand_command('/delegated the bug')
    assert 'delegate_async' in out and 'Investigate the bug.' in out


def test_shell_substitution_runs_before_at_files_and_arguments_are_inlined(tmp_path):
    """`!`cmd`` has to run on the command file as written, before `@path` or `$ARGUMENTS` can inline
    anything -- else a backtick command sitting in an attacker-controlled file, or typed by the
    user as an argument, would be inlined first and then executed as if the command file wrote it.
    """
    host = MemHost({'/proj/notes.txt': 'harmless notes\n!`touch /tmp/pwned`\n'}, root=str(tmp_path),
                   commands={'echo hi': (0, 'hi there')})
    a, _ = fake_agent(host=host, cfg=tmp_path)
    a.approvals = Approvals(tools={'run_shell'}, mode='auto')

    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'inject.md').write_text('Read @/proj/notes.txt and run !`echo hi`.\n')
    out = a.expand_command('/inject')
    assert 'hi there' in out, 'the literal !`echo hi` in the command file itself still runs'
    assert len(host.cmds) == 1 and host.cmds[0][0] == 'echo hi', \
        'a !`cmd` that only appears after @file inlining must never reach the shell'
    assert '!`touch /tmp/pwned`' in out, 'it is inlined as inert text, not executed'

    (tmp_path/'commands'/'argsafe.md').write_text('You said: $ARGUMENTS\n')
    out2 = a.expand_command('/argsafe !`echo hi`')
    assert 'echo hi' in out2 and len(host.cmds) == 1, 'a !`cmd` typed as an argument must not run either'


def test_expand_command_survives_bad_quoting_and_malformed_frontmatter(tmp_path):
    "Free-text arguments and a hand-written command file are not shell code or strict YAML."
    a, _ = fake_agent(cfg=tmp_path)
    (tmp_path/'commands').mkdir()
    (tmp_path/'commands'/'note.md').write_text("Note: $ARGUMENTS\n")
    assert a.expand_command("/note don't break") == "Note: don't break"

    (tmp_path/'commands'/'weird.md').write_text('---\nargument-hint: [pr-number] [priority]\n---\nGo.\n')
    out = a.expand_command('/weird')   # this frontmatter fails to parse; the fallback must not raise
    assert 'Go.' in out


def test_a_note_goes_to_the_agent_when_it_can_keep_one(ui):
    _submit(ui, '#note')
    assert 'usage: #note' in _said(ui)
    _submit(ui, '#note prefer uv')
    assert 'prefer uv' in ui.agent.memory_path.read_text()


def test_the_always_key_keeps_a_rule_and_approves(ui):
    answers = []
    ui.answer = lambda ok, session=False: answers.append((ok, session))
    ui.ask = Ask(tool='run_shell', args={'command': 'pytest -q'})
    ui.on_key(Key('A', 'A'))
    assert answers == [(True, False)] and ui.agent.approvals.rule_for('run_shell', {'command': 'pytest -q'}) == 'allow'
    assert ask_pattern(Ask(tool='edit_file', args={'path': 'a.py'})) == 'a.py'


def test_a_one_shot_prompt_can_come_from_stdin_and_go_out_as_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('from a pipe\n'))
    assert headless_prompt('-') == 'from a pipe'
    assert headless_prompt('typed') == 'typed'
    agent, _ = fake_agent(replies=['pong'])
    assert ask_once(agent, 'ping', as_json=True) == 0
    got = json.loads(capsys.readouterr().out)
    assert got['reply'] == 'pong' and got['session'] == agent.session_id
    assert set(got) == {'reply', 'usage', 'changes', 'activity', 'problems', 'session'}
    assert isinstance(got['usage'], dict) and got['changes'] == [] and got['problems'] == []
