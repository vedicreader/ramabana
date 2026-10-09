"Audio reaching a model that can hear it, and pictures a model sent back."

import os
import re
import struct
import zlib

import pytest
from rich.text import Text

from ramabana.cli import (MAX_IMG_ROWS, Attachment, Picture, draw_png, img_cells, media_parts, media_note,
                          picture, save_media)
from ramabana.core import ModelSpec, accepts

PLACEHOLDER = chr(0x10EEEE)


def _png(w, h):
    "A real single-colour PNG, so the header carries the dimensions a test asserts on."
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def _noise_png(w, h):
    "A PNG zlib cannot shrink, for the tests that need a payload too big for one APC chunk."
    raw = b''.join(b'\x00' + os.urandom(3 * w) for _ in range(h))
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


class _Caps:
    "A `rishi.Caps` stand-in, so a test can state a model's modalities without a model."
    def __init__(self, inp=('text',), out=('text',), source='fastllm'):
        self.inp, self.out, self.source = inp, out, source
    @property
    def known(self): return self.source != 'default'
    def accepts(self, kind): return kind in self.inp
    def fmt(self):
        if not self.known: return 'modalities unknown'
        bits = []
        if self.inp != ('text',): bits.append('in: ' + ' '.join(self.inp))
        if self.out != ('text',): bits.append('out: ' + ' '.join(self.out))
        return ' · '.join(bits)


@pytest.fixture
def caps(monkeypatch):
    "Pin what `spec_caps` answers, so no test depends on a model table or a hub cache."
    box = {}
    monkeypatch.setattr('ramabana.core._caps', lambda mid, rt: box.get('c'))
    def set_(c): box['c'] = c
    return set_


def _spec(name='m', backend='remote'): return ModelSpec(name, backend, name, 128_000)

def _att(tmp_path, name, data=b'x'):
    p = tmp_path/name
    p.write_bytes(data)
    return Attachment(p)


def test_audio_is_withheld_from_a_model_that_cannot_hear_it(tmp_path, caps):
    caps(_Caps(('text', 'image')))
    atts = [_att(tmp_path, 'a.wav'), _att(tmp_path, 'b.png')]
    assert media_parts(atts, _spec()) == [atts[1].data]
    assert 'does not accept audio input' in media_note(atts, _spec())


def test_audio_is_sent_when_the_model_capabilities_are_unknown(tmp_path, caps):
    "Withholding on a silence would turn not-knowing into a smaller agent."
    caps(_Caps(source='default'))
    atts = [_att(tmp_path, 'a.wav', b'RIFF')]
    assert media_parts(atts, _spec()) == [atts[0].data]
    assert accepts(_spec(), 'audio')


def test_a_tall_picture_is_bounded_by_rows_and_not_only_by_columns(tmp_path):
    """Twenty-four columns of a long screenshot is a hundred rows of block. Worse, a placement
    taller than the window can never have all its rows on screen, so it is never drawn at all."""
    p = tmp_path/'tall.png'
    p.write_bytes(_png(300, 3000))
    assert img_cells(p, 80)[1] == MAX_IMG_ROWS
    assert img_cells(p, 80)[0] < 24                  # narrowed to keep the aspect inside the box
    assert img_cells(p, 80, rows=4) == (1, 4)        # a short window bounds it further


def test_a_picture_is_a_direct_placement_and_never_a_placeholder(tmp_path, monkeypatch):
    """Placeholders are the tidier idea and these terminals ignore `U=1`, printing U+10EEEE as a
    missing glyph -- so every picture used to arrive with a block of tofu behind it."""
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = tmp_path/'a.png'
    p.write_bytes(_noise_png(600, 600))      # big enough that the payload must be chunked
    esc = draw_png(p, 40)
    assert esc.startswith('\x1b_G') and esc.endswith('\x1b\\')
    assert 'C=1' in esc and 'U=1' not in esc
    assert PLACEHOLDER not in esc
    # exactly one transmit chunk says "no more"; every earlier one says there is
    assert esc.count('m=0') == 1
    assert esc.count('m=1') == esc.count('\x1b_G') - 2   # the placement carries no `m`


def test_two_pictures_never_share_an_image_id(tmp_path, monkeypatch):
    """The id is what makes a re-placement replace rather than stack. Ids belong to the terminal
    window, not the process, so the counter also starts somewhere no second session will begin:
    both starting at 1 would have each replace the other's pictures, scrollback included."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    (tmp_path/'a.png').write_bytes(_png(64, 64))
    assert picture(tmp_path/'a.png').id != picture(tmp_path/'a.png').id
    assert Picture._n > 1 << 20


# -- generating a picture --------------------------------------------------------------

from ramabana.tools import failed, image_tools


def _gi(session='', **kw):
    return {f.__name__: f for f in image_tools(None, session=session, **kw)}['generate_image']


# -- which model does the drawing ------------------------------------------------------

from ramabana.tools import api_model


def test_the_vendor_prefix_is_stripped_for_the_endpoint():
    "`openai/gpt-5.6-luna` is a model_not_found at the API, which spells it `gpt-5.6-luna`."
    assert api_model('openai/gpt-5.6-luna') == 'gpt-5.6-luna'
    assert api_model('azure/gpt-5') == 'gpt-5'
    assert api_model('gpt-5.6-sol') == 'gpt-5.6-sol'
    assert api_model('anthropic/claude-opus-4-5') == 'anthropic/claude-opus-4-5'


# -- the picture actually reaches the screen -------------------------------------------

def _surface(tmp_path, cols=100, rows=40):
    "A real `Ui` over an emulated tty, plus the list every byte written to it lands in."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    from ramabana.testing import fake_agent

    tty = EmuTty(cols, rows)
    comp = Compositor(tty); comp._register_signals = lambda: None
    asyncio.run(comp.start())
    agent, _ = fake_agent(replies=['ok'])
    ui, writes = Ui(comp, agent), []
    orig = tty.write
    tty.write = lambda s: (writes.append(s), orig(s))[1]
    return ui, tty, writes


PLACED = re.compile(r'\x1b\[(\d+);(\d+)H\x1b_Ga=p,i=(\d+)')


def test_a_picture_is_drawn_on_its_own_blocks_row_not_at_the_cursor(tmp_path, monkeypatch):
    """The bug: a placement lands at the cursor, which after a paint is the input line, and the
    next frame's erase wipes it -- a blank gap where the picture should be. It is placed at the
    row the block actually occupies now, past the gutter, and the cursor is put back after."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    ui.say('a line above', 'note')
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    ui.paint()
    at = PLACED.findall(''.join(writes))
    assert at, 'nothing was placed at all'
    blk = ui.comp.blocks[next(iter(ui.pics))]
    assert {(r, c) for r, c, _ in at} == {('2', '3')}     # under the note, past the two-cell gutter
    assert blk.height == 11 and ui.pics[blk.id].rows == 11
    assert ''.join(writes).rstrip().endswith(f'\x1b[{ui.comp._cursor[0] + 1};{ui.comp._cursor[1] + 1}H')
    tty.close()


def test_a_half_scrolled_picture_is_not_drawn_rows_below_where_it_belongs(tmp_path, monkeypatch):
    """A placement fills its rows downwards from where it lands. While the block straddles the
    top edge only its lower rows are on screen, so drawing there put the whole picture that many
    rows too low, over the blocks beneath it -- and left the inked half blank."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path, rows=20)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    pic = ui.pics[next(iter(ui.pics))]
    assert pic.shown
    for i in range(8): ui.say(f'line {i}', 'note')
    writes.clear()
    ui.paint()
    ws, span = ui.comp._ws, ui.comp._spans[next(iter(ui.pics))]
    assert span[0] < ws < span[0] + span[1], f'it has to straddle the edge: ws={ws} span={span}'
    assert not PLACED.findall(''.join(writes))
    assert not pic.shown
    tty.close()


def test_a_transient_over_a_pictures_rows_takes_the_drawing_off(tmp_path, monkeypatch):
    """The completion menu and the approval options sit above the tail and cover the newest
    transcript rows. The picture was drawn over them, hiding the choices being offered."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path, rows=20)
    for i in range(4): ui.say(f'note {i}', 'note')
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    pic = ui.pics[next(iter(ui.pics))]
    ui.paint()
    assert pic.shown
    writes.clear()
    ui.comp.set_tail(Text('tail'), over=[Text('\n'.join(f'menu {i}' for i in range(8)))])
    assert not PLACED.findall(''.join(writes))
    assert f'a=d,d=i,i={pic.id}' in ''.join(writes)
    writes.clear()
    ui.comp.set_tail(Text('tail'))                       # the menu closes: the picture comes back
    assert PLACED.findall(''.join(writes)) and pic.shown
    tty.close()


from ramabana.testing import FakeBackend


def _be(ctx=128_000):
    "A backend with no chat behind it, which is the shape every fit check is made in."
    return FakeBackend(ModelSpec('m', 'remote', 'm', ctx))


def test_image_bytes_in_a_pending_message_are_not_charged_as_their_own_repr():
    be = _be()
    assert be.pending_tokens([os.urandom(120_000), 'what is this?']) < 5_000


# -- the whole way through a turn ------------------------------------------------------

def _drawing_turn(tmp_path, monkeypatch, cols=100, rows=40, turns=1):
    """A real turn whose one tool call draws, through the real `generate_image`, the real activity
    feed and the real `run_turn`. Returns the surface, every byte written, and how much of the
    reply had streamed at the moment each picture was drawn."""
    import asyncio
    from base64 import b64encode
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.agent import Agent
    from ramabana.cli import Ui, run_turn
    from ramabana.testing import MemHost, ScriptedBackend, Step

    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    monkeypatch.chdir(tmp_path)
    png = _png(600, 600)
    monkeypatch.setattr('shalya.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    said = []

    async def run():
        tty = EmuTty(cols, rows)
        comp = Compositor(tty); comp._register_signals = lambda: None
        await comp.start()
        agent = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), extensions=False, subagents=False, profile='full')
        be = ScriptedBackend(steps=[Step(tool=('generate_image', {'prompt': 'a bottle'})),
                                    Step('Drawn. There it is.')], token_delay=0, tools=agent.tools)
        agent.routing.spec = lambda job='turn', fallback=True: be.spec
        agent._be = agent._be_or_none = lambda job='turn': be
        ui = Ui(comp, agent, loop=asyncio.get_running_loop())
        writes = []
        orig = tty.write
        tty.write = lambda t: (writes.append(t), orig(t))[1]
        hook = ui.show_pic
        ui.show_pic = lambda path: (said.append(ui._reply), hook(path))[1]
        for _ in range(turns): await run_turn(ui, 'draw me a bottle')
        tty.close()
        return ui, ''.join(writes)

    ui, blob = asyncio.run(run())
    return ui, blob, said


def test_a_tools_picture_is_drawn_while_the_turn_is_still_running(tmp_path, monkeypatch):
    """A tool result is text: the model is handed a path, and the frontend used to hear about it
    only in `run_turn`'s `finally`. Every picture then arrived after the turn's last word."""
    ui, blob, said = _drawing_turn(tmp_path, monkeypatch)
    assert len(said) == 1
    assert len(said[0]) < len(ui._reply), 'the reply was already complete when the picture landed'
    assert blob.count('a=t,f=100') == 1
    assert PLACED.findall(blob)


def test_a_picture_a_tool_saved_is_not_saved_a_second_time(tmp_path, monkeypatch):
    "`last_media` reads the file back as bytes; saving those again writes the same picture twice."
    ui, blob, said = _drawing_turn(tmp_path, monkeypatch)
    files = sorted(p.name for p in (tmp_path/'media').glob('*'))
    assert files == ['generated-1.png'], files
    assert ui.agent.resp_media == []
    assert len(ui.agent.last_media) == 1


def test_the_image_group_reads_the_turns_model_on_every_call(tmp_path, monkeypatch, caps):
    """`image_tools` read `get_spec()` once, at build time. Every large-window model shares one
    budget, so `set_model` did not rebuild the tools, and the group kept answering for the model
    the session had already moved off: it drew as a model that cannot draw, at the old model id."""
    from base64 import b64encode
    png = b'\x89PNG\r\n\x1a\nx'
    drawing = _Caps(('text', 'image'), ('text',)); drawing.tools = ('image',)
    flat = _Caps(('text', 'image'), ('text',))                  # same windows, cannot draw
    seen = {}

    current = {'spec': _spec('openai/gpt-5.6-luna')}
    by_model = {'openai/gpt-5.6-luna': drawing, 'anthropic/claude-opus-4-5': flat}
    monkeypatch.setattr('ramabana.core._caps', lambda model_id, backend: by_model[model_id])
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_responses',
                        lambda prompt, model, timeout=300: seen.update(responses=model) or
                        {'output': [{'type': 'image_generation_call', 'result': b64encode(png).decode()}]})
    monkeypatch.setattr('shalya.tools._post_image',
                        lambda *a, **kw: seen.update(images=kw.get('model')) or
                        [{'b64_json': b64encode(png).decode()}])

    gi = _gi(session=str(tmp_path), get_spec=lambda: current['spec'])
    assert not failed(gi('a bottle'))
    assert seen == {'responses': 'openai/gpt-5.6-luna'}, seen   # its own model drew it

    seen.clear()
    current['spec'] = _spec('anthropic/claude-opus-4-5')        # the same built tool, a new model
    assert not failed(gi('a bottle'))
    assert 'responses' not in seen, 'it drew as a model that cannot draw'
    assert seen == {'images': 'gpt-image-1'}, seen              # the endpoint, not the stale id


