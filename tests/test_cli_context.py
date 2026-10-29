"The surface's context: one function names it for the hint row and for Sanketa, and a change of context sets the terminal title once."
import asyncio, threading

from teleprint.keys import Key

from ramabana import cli
from test_cli_keys import _keys_scene, _slow


def _spy(tty):
    "The chunks written to `tty` from now on."
    sent, write = [], tty.write
    tty.write = lambda data: (sent.append(data), write(data))[1]
    return sent


def _titles(sent): return [s for s in sent if isinstance(s, str) and '\x1b]2;' in s]


def test_the_context_names_the_state_the_hint_row_shows():
    async def body(u, agent, tty):
        seen = {'idle': u.context()}
        u.buf.insert('fix the'); seen['typing'] = u.context()
        u.buf.clear()
        u.menu = cli.TaskMenu(lambda: [dict(kind='watch', id='w1', label='src', state='running', detail='x')])
        seen['tasks'] = u.context()
        u.menu = None; u.enter_transcript(); seen['transcript'] = u.context()
        u.leave_transcript()
        u.start_turn(_slow()); seen['running'] = u.context()
        u.buf.insert('later'); u.start_turn(u.on_key(Key('alt+enter'))); seen['waiting'] = u.context()
        threading.Thread(target=lambda: agent.approvals.request('create_file', {'path': '/proj/a.md', 'text': 'x'}), daemon=True).start()
        for _ in range(40):
            await asyncio.sleep(.02)
            if u.ask is not None: break
        seen['approval'] = u.context()
        u.enter_transcript(); over_ask = u.context(); u.leave_transcript()
        assert over_ask == 'transcript', 'the browsing view takes the keys first, even over a pending approval'
        u.on_key(Key('ctrl+c'))
        assert seen == {c['id']: c['id'] for c in cli.CONTEXTS}
    _keys_scene(body)


def test_a_change_of_context_sets_the_title_once_and_a_repaint_sets_none():
    async def body(u, agent, tty):
        sent = _spy(tty)
        u.paint()
        assert _titles(sent) == ['\x1b]2;ramabana · idle\x07']
        u.paint(); u.paint()
        assert len(_titles(sent)) == 1, 'a repaint in the same context writes no title'
        u.buf.insert('x'); u.paint()
        assert _titles(sent)[1:] == ['\x1b]2;ramabana · typing\x07']
        u.buf.insert('y'); u.paint()
        assert len(_titles(sent)) == 2
        u.buf.clear(); u.enter_transcript()
        assert _titles(sent)[2:] == ['\x1b]2;ramabana · transcript\x07'], 'opening the view paints nothing, so it announces itself'
        u.leave_transcript()
        assert _titles(sent)[3:] == ['\x1b]2;ramabana · idle\x07']
        await u.lend(lambda: None)
        assert _titles(sent)[4:] == ['\x1b]2;ramabana · idle\x07'], 'a borrower may have set its own title, so the same context is announced again'
    _keys_scene(body)
