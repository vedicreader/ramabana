"""The ACP seam, driven the way an editor drives it.

Every test here spawns the agent as a subprocess and speaks JSON-RPC to it, so what is covered
is the framing an editor exercises rather than a Python call. The model is scripted; the host,
the tools, the gate and the protocol are real. Nothing loads a model.
"""

import asyncio
import os
import sys
from pathlib import Path

import acp
import pytest
from acp.schema import (AllowedOutcome, ClientCapabilities, DeniedOutcome, FileSystemCapabilities,
                        RequestPermissionResponse, TerminalExitStatus, TerminalOutputResponse,
                        CreateTerminalResponse, WaitForTerminalExitResponse)


pytestmark = pytest.mark.slow   # every test spawns a subprocess; 147s of the suite

HERE = Path(__file__).parent


class Editor(acp.Client):
    "What an editor does: collect the updates, and answer the permission requests."

    caps = None

    def __init__(self, answer='allow_once'):
        self.answer, self.updates, self.asked = answer, [], []

    async def session_update(self, session_id, update, **kw): self.updates.append(update)

    async def request_permission(self, session_id, tool_call, options, **kw):
        self.asked.append(tool_call)
        if self.answer is None: return RequestPermissionResponse(outcome=DeniedOutcome(outcome='cancelled'))
        return RequestPermissionResponse(outcome=AllowedOutcome(outcome='selected', option_id=self.answer))

    async def read_text_file(self, session_id, path, line=None, limit=None, **kw):
        raise acp.RequestError.method_not_found('fs/read_text_file')

    async def write_text_file(self, session_id, path, content, **kw):
        raise acp.RequestError.method_not_found('fs/write_text_file')


class Buffers(Editor):
    "An editor that answers for its own unsaved buffers."

    caps = ClientCapabilities(fs=FileSystemCapabilities(read_text_file=True, write_text_file=True))

    def __init__(self, answer='allow_always', buffers=None):
        super().__init__(answer)
        self.buffers, self.wrote = dict(buffers or {}), {}

    async def read_text_file(self, session_id, path, line=None, limit=None, **kw):
        name = Path(path).name
        if name not in self.buffers: raise acp.RequestError.resource_not_found(path)
        return acp.schema.ReadTextFileResponse(content=self.buffers[name])

    async def write_text_file(self, session_id, path, content, **kw):
        self.wrote[Path(path).name] = content
        self.buffers[Path(path).name] = content
        return None


class Terminals(Editor):
    "An editor that runs the command itself, so the person watches it happen."

    caps = ClientCapabilities(terminal=True)

    def __init__(self, answer='allow_always'):
        super().__init__(answer)
        self.ran, self.released = [], []

    async def create_terminal(self, session_id, command, args=None, env=None, cwd=None,
                              output_byte_limit=None, **kw):
        self.ran.append((command, list(args or []), cwd))
        return CreateTerminalResponse(terminal_id='term-1')

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        return WaitForTerminalExitResponse(exit_code=0)

    async def terminal_output(self, session_id, terminal_id, **kw):
        return TerminalOutputResponse(output='hello from the editor', truncated=False,
                                      exit_status=TerminalExitStatus(exit_code=0))

    async def release_terminal(self, session_id, terminal_id, **kw):
        self.released.append(terminal_id)
        return None


def kinds(ups): return [getattr(u, 'session_update', '?') for u in ups]

def said(ups):
    return ''.join(getattr(getattr(u, 'content', None), 'text', '')
                   for u in ups if getattr(u, 'session_update', '') == 'agent_message_chunk')

def details(ups):
    "Every piece of tool-call content the editor was shown, as text."
    out = []
    for u in ups:
        for c in (getattr(u, 'content', None) or []):
            inner = getattr(c, 'content', None)
            if getattr(inner, 'text', None): out.append(inner.text)
    return '\n'.join(out)


async def drive(tmp, editor, prompt='fix the import', script='edit', disk='import b\n'):
    "One whole exchange against a freshly spawned agent."
    (tmp/'a.py').write_text(disk)
    env = {**os.environ, 'ACP_ROOT': str(tmp), 'ACP_SCRIPT': script,
           'PYTHONPATH': str(HERE.parent), 'RAMABANA_CFG': str(tmp/'.cfg')}
    async with acp.spawn_agent_process(editor, sys.executable, str(HERE/'acp_serve.py'),
                                       env=env) as (conn, _):
        init = await conn.initialize(protocol_version=acp.PROTOCOL_VERSION,
                                     client_capabilities=type(editor).caps)
        new = await conn.new_session(cwd=str(tmp))
        res = await conn.prompt(session_id=new.session_id, prompt=[acp.text_block(prompt)])
        return init, new, res


def run(coro, t=90): return asyncio.run(asyncio.wait_for(coro, t))


# ---- the wire -------------------------------------------------------------------------

@pytest.mark.parametrize('answer,created', [('allow_once', True), (None, False)])
def test_a_whole_turn_over_the_real_wire_protocol(tmp_path, answer, created):
    ed = Editor(answer)
    init, new, res = run(drive(tmp_path, ed))
    assert init.protocol_version == acp.PROTOCOL_VERSION
    assert init.agent_capabilities.prompt_capabilities.image is True
    assert init.agent_capabilities.prompt_capabilities.audio is True
    assert res.stop_reason == 'end_turn' and new.session_id
    assert 'Looking at it now.' in said(ed.updates)
    assert 'tool_call' in kinds(ed.updates)
    assert (tmp_path/'b.py').exists() is created

def test_a_gated_call_is_one_entry_in_the_editor_rather_than_two(tmp_path):
    "The id the dialog was opened under has to be the id the call finishes under."
    ed = Editor('allow_once')
    run(drive(tmp_path, ed))
    asked = {u.tool_call_id for u in ed.asked}
    finished = {u.tool_call_id for u in ed.updates
                if getattr(u, 'status', None) == 'completed' and getattr(u, 'tool_call_id', None)}
    assert asked and asked <= finished, (asked, finished)
    # and no second entry was opened for the same call
    started = [getattr(u, 'tool_call_id', None) for u in ed.updates
               if getattr(u, 'session_update', '') == 'tool_call']
    assert len(started) == len(set(started)), started


# ---- the editor answers for its own files ---------------------------------------------

def test_a_write_goes_to_the_editor_and_not_behind_its_back_to_disk(tmp_path):
    ed = Buffers(buffers={'a.py': 'import b\n'})
    run(drive(tmp_path, ed))
    assert 'b.py' in ed.wrote and ed.wrote['b.py'] == 'B = 1\n'
    assert not (tmp_path/'b.py').exists(), 'the editor owns the file, so nothing should be on disk'


# ---- the editor runs the command ------------------------------------------------------

def test_a_command_runs_in_the_editors_terminal_and_its_output_comes_back(tmp_path):
    ed = Terminals()
    _, _, res = run(drive(tmp_path, ed, script='shell'))
    assert res.stop_reason == 'end_turn'
    assert ed.ran, 'the editor was never asked to open a terminal'
    command, args, cwd = ed.ran[0]
    assert args[:1] == ['-c'] and 'echo hello' in args[-1], (command, args)
    assert cwd == str(tmp_path)
    assert 'hello from the editor' in details(ed.updates)


class BrokenTerminal(Terminals):
    "An editor whose terminal starts the command and then stops answering about it."
    async def wait_for_terminal_exit(self, session_id, terminal_id, **kw):
        raise acp.RequestError.internal_error({'details': 'the terminal went away'})


def test_a_terminal_that_dies_after_starting_the_command_does_not_run_it_again(tmp_path):
    "The command already ran once in the editor. Falling back locally would run it twice."
    ed = BrokenTerminal()
    _, _, res = run(drive(tmp_path, ed, script='marker'))
    assert res.stop_reason == 'end_turn'
    assert ed.ran, 'the editor was never asked to open a terminal'
    assert not (tmp_path/'marker.txt').exists(), 'the command was run a second time locally'
    assert 'terminal failed after starting' in details(ed.updates)


# ---- sessions the editor can name and come back to ------------------------------------

def _history(tmp, rows):
    "A cfg directory holding conversations, the way one accumulates them."
    import json
    d = tmp/'.cfg'
    d.mkdir(parents=True, exist_ok=True)
    (d/'agent-history.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')

def _turn(session, prompt, reply, model=''):
    # model empty on purpose: `resume_session` only calls `set_model` when one was recorded,
    # and this test is about which conversation is replayed, not about routing
    return {'at': 1, 'session': session, 'turn_id': '1', 'branch_id': 'main', 'model': model,
            'prompt': prompt, 'reply': reply, 'error': '', 'plan': {}, 'usage': {},
            'usage_label': '', 'activity': []}

OLD, NEW = 'agent_20260101-000000-000000', 'agent_20260102-000000-000000'

async def _load(tmp, editor, session_id):
    (tmp/'a.py').write_text('import b\n')
    env = {**os.environ, 'ACP_ROOT': str(tmp), 'ACP_SCRIPT': 'view', 'PYTHONPATH': str(HERE.parent)}
    async with acp.spawn_agent_process(editor, sys.executable, str(HERE/'acp_serve.py'),
                                       env=env) as (conn, _):
        await conn.initialize(protocol_version=acp.PROTOCOL_VERSION,
                              client_capabilities=type(editor).caps)
        return await conn.load_session(cwd=str(tmp), session_id=session_id)


def test_loading_a_session_replays_that_conversation_and_not_another(tmp_path):
    _history(tmp_path, [_turn(OLD, 'FIRST project question', 'first answer'),
                        _turn(NEW, 'SECOND project question', 'second answer')])
    ed = Editor()
    run(_load(tmp_path, ed, OLD))
    replayed = ''.join(getattr(getattr(u, 'content', None), 'text', '') for u in ed.updates)
    assert 'FIRST project question' in replayed
    assert 'SECOND' not in replayed, 'the editor was shown an unrelated conversation'


def test_every_console_script_resolves():
    """A rename that misses `[project.scripts]` leaves a binary that fails only when a user runs it.

    `ramabana/acp.py` shadowed the `acp` package it imports, so it became `ramabana.racp`. The
    entry point kept pointing at `ramabana.acp:main`, which no test touched: the suite imports
    modules directly, and nothing but an editor launching `ramabana-acp` would have found it.
    """
    import importlib, tomllib
    from pathlib import Path
    cfg = tomllib.loads((Path(__file__).parent.parent/'pyproject.toml').read_text())
    scripts = cfg['project']['scripts']
    assert 'ramabana-acp' in scripts
    for name, target in scripts.items():
        mod, _, fn = target.partition(':')
        m = importlib.import_module(mod)
        assert callable(getattr(m, fn, None)), f'{name} = {target!r} does not resolve'


