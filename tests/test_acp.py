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

from ramabana.acp import KIND, PLAN, TOOL, EditorHost, blocks

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

def contents(ups, kind):
    return [c for u in ups for c in (getattr(u, 'content', None) or []) if getattr(c, 'type', '') == kind]


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


# ---- the mappings ----------------------------------------------------------------------

def test_text_blocks_arrive_as_one_message():
    text, media = blocks([acp.text_block('why does'), acp.text_block('it fail?')])
    assert text == 'why does\n\nit fail?' and media == []

def test_an_image_block_arrives_as_the_bytes_a_content_part_is_made_of():
    import base64
    png = b'\x89PNG\r\n\x1a\n'
    text, media = blocks([acp.text_block('what is this'),
                          acp.image_block(base64.b64encode(png).decode(), 'image/png')])
    assert media == [png] and text == 'what is this'

def test_audio_is_dropped_with_a_reason_when_the_model_cannot_hear_it():
    import base64, ramabana.core as core
    class Caps:
        known = True
        def accepts(self, kind): return kind != 'audio'
    class Spec: model_id, backend, local = 'm', 'remote', False
    was = core._caps
    core._caps = lambda mid, rt: Caps()
    try:
        text, media = blocks([acp.audio_block(base64.b64encode(b'RIFF').decode(), 'audio/wav')], Spec())
    finally: core._caps = was
    assert media == [] and 'does not accept audio' in text

def test_a_resource_link_becomes_the_at_path_the_harness_understands():
    class Link: type, uri = 'resource_link', 'file:///proj/a.py'
    assert blocks([Link()])[0] == '@file:///proj/a.py'

def test_every_kind_the_harness_names_has_somewhere_to_go_in_an_editor():
    import typing
    from acp.schema import ToolCallStart
    known = set(typing.get_args(typing.get_args(ToolCallStart.model_fields['kind'].annotation)[0]))
    assert set(KIND.values()) <= known and set(TOOL.values()) <= known
    assert set(PLAN.values()) == {'pending', 'in_progress', 'completed'}


# ---- a host with no editor behind it ---------------------------------------------------

def test_an_unattached_editor_host_is_a_local_host():
    h = EditorHost(['.'])
    assert (h.can_read, h.can_write, h.can_run) == (False, False, False)

def test_the_capability_probe_never_reaches_the_editor():
    "`tools_for` asks whether commands can be run with an empty one, and must spawn nothing."
    assert EditorHost(['.']).run_cmd('') == (0, '')


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
    ed = Editor('allow_once')
    run(drive(tmp_path, ed))
    gated = {u.tool_call_id for u in ed.asked}
    assert gated <= {getattr(u, 'tool_call_id', None) for u in ed.updates}

def test_a_new_file_reaches_the_editor_as_a_diff_to_read(tmp_path):
    ed = Editor('allow_once')
    run(drive(tmp_path, ed))
    diffs = contents(ed.updates, 'diff')
    assert diffs and any(d.path.endswith('b.py') for d in diffs)

def test_each_write_is_gated_on_its_own_unless_the_session_was_allowed(tmp_path):
    ed = Editor('allow_once')
    run(drive(tmp_path, ed))
    assert len(ed.asked) == 2

def test_allowing_the_session_asks_once_and_lets_the_rest_through(tmp_path):
    ed = Editor('allow_always')
    run(drive(tmp_path, ed))
    assert len(ed.asked) == 1
    assert (tmp_path/'b.py').exists() and (tmp_path/'c.py').exists()

def test_a_refusal_closes_the_tool_call_rather_than_leaving_it_pending(tmp_path):
    ed = Editor(None)
    run(drive(tmp_path, ed))
    failed = {getattr(u, 'tool_call_id', None) for u in ed.updates
              if getattr(u, 'status', None) == 'failed'}
    assert {u.tool_call_id for u in ed.asked} <= failed
    assert not (tmp_path/'b.py').exists()

def test_the_editor_is_offered_the_harness_own_commands(tmp_path):
    ed = Editor()
    run(drive(tmp_path, ed))
    upd = [u for u in ed.updates if getattr(u, 'session_update', '') == 'available_commands_update']
    assert upd
    assert {'model', 'sessions', 'resume', 'compact', 'plan'} <= {c.name for c in upd[0].available_commands}

def test_a_slash_command_is_answered_without_running_a_turn(tmp_path):
    ed = Editor()
    _, _, res = run(drive(tmp_path, ed, prompt='/tools'))
    assert res.stop_reason == 'end_turn' and 'view_file' in said(ed.updates)
    assert not ed.asked and not (tmp_path/'b.py').exists()


# ---- the editor answers for its own files ---------------------------------------------

def test_a_file_is_viewed_as_the_editor_has_it_rather_than_as_disk_has_it(tmp_path):
    "The point of `fs/read_text_file`: an unsaved buffer is what the person is looking at."
    ed = Buffers(buffers={'a.py': 'BUFFER = 1\n'})
    run(drive(tmp_path, ed, script='view', disk='DISK = 0\n'))
    shown = details(ed.updates)
    assert 'BUFFER' in shown and 'DISK' not in shown

def test_a_write_goes_to_the_editor_and_not_behind_its_back_to_disk(tmp_path):
    ed = Buffers(buffers={'a.py': 'import b\n'})
    run(drive(tmp_path, ed))
    assert 'b.py' in ed.wrote and ed.wrote['b.py'] == 'B = 1\n'
    assert not (tmp_path/'b.py').exists(), 'the editor owns the file, so nothing should be on disk'

def test_an_editor_that_cannot_serve_a_read_falls_back_rather_than_losing_the_turn(tmp_path):
    "`Buffers` raises for any file it has no buffer for; the turn must still finish from disk."
    ed = Buffers(buffers={})
    _, _, res = run(drive(tmp_path, ed, script='view', disk='DISK = 0\n'))
    assert res.stop_reason == 'end_turn'
    assert 'DISK' in details(ed.updates)


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

def test_the_terminal_is_shown_inside_the_tool_call_that_started_it(tmp_path):
    ed = Terminals()
    run(drive(tmp_path, ed, script='shell'))
    refs = contents(ed.updates, 'terminal')
    assert refs and refs[0].terminal_id == 'term-1'

def test_a_terminal_is_released_when_the_command_is_done(tmp_path):
    ed = Terminals()
    run(drive(tmp_path, ed, script='shell'))
    assert ed.released == ['term-1']
