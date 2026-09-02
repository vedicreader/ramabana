"Audio reaching a model that can hear it, and pictures a model sent back."

import os
import re
import struct
import zlib
from pathlib import Path

import pytest
from rich.text import Text

from ramabana.cli import (MAX_IMG_DRAW, MAX_IMG_ROWS, Attachment, Picture, draw_png, img_cells,
                          kitty_graphics, media_line, media_parts, media_note, picture, png_size,
                          save_media, sendable)
from ramabana.core import ModelSpec, accepts, model_note, spec_caps

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


def test_audio_reaches_a_model_that_can_hear_it(tmp_path, caps):
    caps(_Caps(('text', 'image', 'audio')))
    atts = [_att(tmp_path, 'a.wav', b'RIFF'), _att(tmp_path, 'b.png')]
    assert media_parts(atts, _spec()) == [a.data for a in atts]
    note = media_note(atts, _spec())
    assert 'The audio above is attached' in note and 'by path only' not in note


def test_audio_is_sent_when_the_model_capabilities_are_unknown(tmp_path, caps):
    "Withholding on a silence would turn not-knowing into a smaller agent."
    caps(_Caps(source='default'))
    atts = [_att(tmp_path, 'a.wav', b'RIFF')]
    assert media_parts(atts, _spec()) == [atts[0].data]
    assert accepts(_spec(), 'audio')


def test_audio_is_sent_when_rishi_is_too_old_to_have_an_opinion(tmp_path, caps):
    "`spec_caps` answering None is a different thing from a model whose modalities are unknown."
    caps(None)
    atts = [_att(tmp_path, 'a.wav', b'RIFF')]
    assert spec_caps(_spec()) is None
    assert media_parts(atts, _spec()) == [atts[0].data]


def test_no_spec_at_all_sends_everything(tmp_path):
    "A caller that cannot name a model gets the permissive path, not the restrictive one."
    atts = [_att(tmp_path, 'a.wav', b'RIFF'), _att(tmp_path, 'b.png')]
    assert sendable(atts) == {'image', 'audio'}
    assert media_parts(atts) == [a.data for a in atts]


def test_pictures_are_always_sendable_whatever_the_model_claims(tmp_path, caps):
    caps(_Caps(('text',)))
    atts = [_att(tmp_path, 'b.png')]
    assert media_parts(atts, _spec()) == [atts[0].data]


def test_the_banner_names_the_modalities_a_model_has(caps):
    caps(_Caps(('text', 'image', 'audio', 'video'), ('text', 'image')))
    note = model_note(_spec('gemini-2.5-flash-image'))
    assert 'in: text image audio video' in note and 'out: text image' in note


def test_the_banner_says_unknown_rather_than_text_only_for_an_untabled_model(caps):
    caps(_Caps(source='default'))
    assert 'modalities unknown' in model_note(_spec('veo-3.0-generate-001'))


def test_the_banner_is_silent_about_a_plain_text_model(caps):
    caps(_Caps(('text',), ('text',)))
    note = model_note(_spec('gpt-5'))
    assert 'in:' not in note and 'out:' not in note and 'unknown' not in note


def test_the_banner_omits_modalities_where_rishi_cannot_say(caps):
    caps(None)
    note = model_note(_spec('gpt-5'))
    assert 'unknown' not in note and note.endswith('128k ctx')


def test_a_terminal_without_kitty_graphics_gets_a_path_not_escape_bytes(tmp_path, monkeypatch):
    for k in ('KITTY_WINDOW_ID', 'GHOSTTY_RESOURCES_DIR', 'TERM', 'TERM_PROGRAM'):
        monkeypatch.delenv(k, raising=False)
    p = save_media({'mime': 'image/png', 'data': b'\x89PNG\r\n\x1a\nx'}, tmp_path)
    assert not kitty_graphics()
    assert draw_png(p) == ''
    assert media_line(p).startswith('saved  ')
    assert '\x1b' not in media_line(p)


def test_a_non_png_is_saved_but_never_drawn(tmp_path, monkeypatch):
    "kittytgp is PNG-only, so a webp takes the path route even in a kitty terminal."
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = save_media({'mime': 'image/webp', 'data': b'RIFFwebp'}, tmp_path)
    assert p.suffix == '.webp' and p.exists()
    assert draw_png(p) == ''


def test_a_truncated_png_is_refused_rather_than_measured(tmp_path, monkeypatch):
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = save_media({'mime': 'image/png', 'data': b'not a png at all'}, tmp_path)
    assert png_size(p) is None
    assert draw_png(p) == ''


def test_a_picture_is_measured_from_its_header_and_fitted_to_the_width(tmp_path):
    p = tmp_path/'a.png'
    p.write_bytes(_png(1254, 1254))
    assert png_size(p) == (1254, 1254)
    assert img_cells(p, 80) == (24, 11)      # clamped to MAX_IMG_COLS, square on screen
    assert img_cells(p, 12) == (12, 6)
    assert img_cells(tmp_path/'wide.png', 40) is None


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


def test_the_bytes_and_the_drawing_are_separate_escapes(tmp_path, monkeypatch):
    """One is a megabyte and one is forty bytes. Only the split makes a picture survive the
    compositor: the payload goes once, and the drawing is cheap enough to repeat every frame."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    p = tmp_path/'a.png'
    p.write_bytes(_noise_png(600, 600))
    pic = picture(p, 40)
    assert (pic.cols, pic.rows) == (24, 11)
    assert 'a=t' in pic.send() and 'a=p' not in pic.send()
    assert len(pic.send()) > 2 * 4096              # chunked, as the protocol requires
    assert pic.place() == f'\x1b_Ga=p,i={pic.id},p=1,c=24,r=11,C=1,q=2\x1b\\'
    assert pic.clear() == f'\x1b_Ga=d,d=i,i={pic.id},p=1,q=2\x1b\\'
    assert len(pic.gap().plain.split('\n')) == 11  # eleven rows of text under eleven rows of cells


def test_the_reserved_rows_name_the_file_so_nothing_is_ever_a_blank_hole(tmp_path, monkeypatch):
    """The drawing is above the cells it covers, so the name shows only where the picture does not:
    the browsing view, a fold's summary row, and a terminal that drew nothing."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    blk = ui.comp.blocks[next(iter(ui.pics))]
    assert ui.transcript.block_text(blk) == str(p)          # copy and search get the path
    assert blk.body[0].plain.split('\n')[0] == p.name
    ui.comp.toggle(blk)
    assert p.name in ''.join(s.text for s in ui.comp._block_rows(blk)[0][1])
    tty.close()


def test_two_pictures_never_share_an_image_id(tmp_path, monkeypatch):
    """The id is what makes a re-placement replace rather than stack. Ids belong to the terminal
    window, not the process, so the counter also starts somewhere no second session will begin:
    both starting at 1 would have each replace the other's pictures, scrollback included."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    (tmp_path/'a.png').write_bytes(_png(64, 64))
    assert picture(tmp_path/'a.png').id != picture(tmp_path/'a.png').id
    assert Picture._n > 1 << 20


def test_a_file_this_terminal_cannot_draw_is_no_picture_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    (tmp_path/'a.webp').write_bytes(b'RIFFwebp')
    (tmp_path/'bad.png').write_bytes(b'not a png at all')
    assert picture(tmp_path/'a.webp') is None       # kittytgp is PNG-only, and so is this
    assert picture(tmp_path/'bad.png') is None      # no readable header, nothing to size it by
    monkeypatch.setenv('RAMABANA_KITTY', '0')
    (tmp_path/'ok.png').write_bytes(_png(64, 64))
    assert picture(tmp_path/'ok.png') is None


def test_generated_pictures_land_beside_the_session_without_overwriting(tmp_path):
    png = b'\x89PNG\r\n\x1a\nx'
    a = save_media({'mime': 'image/png', 'data': png}, tmp_path)
    b = save_media({'mime': 'image/png', 'data': png + b'y'}, tmp_path)
    assert a.parent == tmp_path/'media'
    assert (a.name, b.name) == ('image-1.png', 'image-2.png')
    assert a.read_bytes() != b.read_bytes()


def test_a_mime_the_table_does_not_know_still_lands_somewhere_sensible(tmp_path):
    assert save_media({'mime': 'image/avif', 'data': b'x'}, tmp_path).suffix == '.avif'


# -- generating a picture --------------------------------------------------------------

from ramabana.testing import MemHost
from ramabana.tools import failed, image_available, image_tools, tools_for


def _gi(session='', **kw):
    return {f.__name__: f for f in image_tools(None, session=session, **kw)}['generate_image']


def test_generate_image_refuses_without_a_key_rather_than_calling(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert not image_available()
    r = _gi()('a cat')
    assert failed(r) and 'OPENAI_API_KEY' in r


def test_an_unknown_size_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    called = []
    monkeypatch.setattr('shalya.tools._post_image', lambda *a, **kw: called.append(a))
    assert failed(_gi()('a cat', size='4096x4096'))
    assert called == []


def test_a_generated_picture_lands_beside_the_session(tmp_path, monkeypatch):
    from base64 import b64encode
    png = b'\x89PNG\r\n\x1a\nx'
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    out = _gi(session=str(tmp_path))('a cat')
    assert not failed(out)
    p = Path(out.strip())
    assert p.parent == tmp_path/'media' and p.read_bytes() == png


def test_an_endpoint_failure_is_a_refusal_not_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    def boom(*a, **kw): raise RuntimeError('502 upstream')
    monkeypatch.setattr('shalya.tools._post_image', boom)
    r = _gi(session=str(tmp_path))('a cat')
    assert failed(r) and '502 upstream' in r


def test_an_empty_reply_is_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_image', lambda *a, **kw: [])
    assert failed(_gi(session=str(tmp_path))('a cat'))


def test_the_tool_is_registered_only_where_the_key_is(monkeypatch):
    h = MemHost({'/proj/a.py': 'x = 1'})
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    assert 'generate_image' in [f.__name__ for f in tools_for(h)]
    assert 'generate_image' not in [f.__name__ for f in tools_for(h, drop={'image'})]
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert 'generate_image' not in [f.__name__ for f in tools_for(h)]


# -- which terminals can draw ----------------------------------------------------------

from ramabana.cli import KITTY_PROGRAM, KITTY_TERM


@pytest.fixture
def bare_term(monkeypatch):
    "No terminal identity and no override, so each test states only what it means to."
    for k in ('KITTY_WINDOW_ID', 'GHOSTTY_RESOURCES_DIR', 'TERM', 'TERM_PROGRAM',
              'RAMABANA_KITTY', 'LEELA_KITTY'):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.parametrize('term', ('kaku', 'xterm-kitty', 'wezterm', 'ghostty'))
def test_a_terminal_that_speaks_the_protocol_is_recognised(bare_term, term):
    bare_term.setenv('TERM', term)
    assert kitty_graphics()


def test_leelas_terminal_is_not_mistaken_for_one_that_can_draw(bare_term):
    "leela runs xterm.js, whose image addon has no unicode-placeholder support."
    bare_term.setenv('TERM', 'xterm-256color')
    assert not kitty_graphics()


def test_the_env_override_settles_it_either_way(bare_term):
    "The list can only name terminals known when it was written; a user may know better."
    bare_term.setenv('TERM', 'xterm-256color')
    bare_term.setenv('RAMABANA_KITTY', '1')
    assert kitty_graphics()
    bare_term.setenv('TERM', 'kaku')
    bare_term.setenv('RAMABANA_KITTY', '0')
    assert not kitty_graphics()


def test_leela_may_spell_the_override_with_its_own_prefix(bare_term):
    bare_term.setenv('TERM', 'xterm-256color')
    bare_term.setenv('LEELA_KITTY', '1')
    assert kitty_graphics()


# -- which model does the drawing ------------------------------------------------------

from ramabana.tools import api_model, draws_itself


def test_a_model_that_draws_for_itself_is_told_apart_from_one_that_cannot(caps):
    caps(_Caps(('text', 'image'), ('text',)))
    assert not draws_itself(_spec())
    c = _Caps(('text', 'image'), ('text',)); c.tools = ('image',)
    caps(c)
    assert draws_itself(_spec())
    caps(None)
    assert not draws_itself(_spec())
    assert not draws_itself(None)


def test_the_vendor_prefix_is_stripped_for_the_endpoint():
    "`openai/gpt-5.6-luna` is a model_not_found at the API, which spells it `gpt-5.6-luna`."
    assert api_model('openai/gpt-5.6-luna') == 'gpt-5.6-luna'
    assert api_model('azure/gpt-5') == 'gpt-5'
    assert api_model('gpt-5.6-sol') == 'gpt-5.6-sol'
    assert api_model('anthropic/claude-opus-4-5') == 'anthropic/claude-opus-4-5'


def test_a_drawing_model_draws_as_itself_rather_than_delegating(tmp_path, monkeypatch, caps):
    from base64 import b64encode
    png = b'\x89PNG\r\n\x1a\nx'
    c = _Caps(('text', 'image'), ('text',)); c.tools = ('image',)
    caps(c)
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    seen = {}
    def fake(prompt, model, timeout=300):
        seen['model'] = model
        return {'output': [{'type': 'image_generation_call', 'result': b64encode(png).decode()}]}
    monkeypatch.setattr('shalya.tools._post_responses', fake)
    monkeypatch.setattr('shalya.tools._post_image', lambda *a, **kw: pytest.fail('delegated'))
    gi = _gi(session=str(tmp_path), get_spec=lambda: _spec('openai/gpt-5.6-luna'))
    out = gi('a bottle')
    assert not failed(out)
    assert seen['model'] == 'openai/gpt-5.6-luna'      # api_model strips it at the wire
    assert Path(out.strip()).read_bytes() == png


def test_a_model_that_cannot_draw_falls_back_to_the_images_endpoint(tmp_path, monkeypatch, caps):
    from base64 import b64encode
    png = b'\x89PNG\r\n\x1a\nx'
    caps(_Caps(('text', 'image'), ('text',)))
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_responses', lambda *a, **kw: pytest.fail('should not ask'))
    monkeypatch.setattr('shalya.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    gi = _gi(session=str(tmp_path), get_spec=lambda: _spec('anthropic/claude-opus-4-5'))
    assert Path(gi('a bottle').strip()).read_bytes() == png


def test_a_drawing_model_that_returns_no_picture_is_a_refusal(tmp_path, monkeypatch, caps):
    c = _Caps(('text', 'image'), ('text',)); c.tools = ('image',)
    caps(c)
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_responses',
                        lambda *a, **kw: {'output': [{'type': 'message'}]})
    gi = _gi(session=str(tmp_path), get_spec=lambda: _spec('openai/gpt-5.6-luna'))
    assert failed(gi('a bottle'))


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


def _painted(png_bytes, tmp_path, cols=100, rows=40, media=None):
    "Every byte the compositor and the out-of-band write put on an emulated tty."
    ui, tty, writes = _surface(tmp_path, cols, rows)
    ui.show_media(media or [{'mime': 'image/png', 'data': png_bytes}], session=str(tmp_path))
    ui.paint()
    tty.close()
    return ''.join(writes)


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


def test_the_payload_goes_once_and_the_drawing_goes_every_frame(tmp_path, monkeypatch):
    "A megabyte per repaint would make the surface unusable; forty bytes per repaint is free."
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    for _ in range(4): ui.paint()
    blob = ''.join(writes)
    assert blob.count('a=t,f=100') == 1
    assert len(PLACED.findall(blob)) >= 5
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


def test_a_picture_the_window_slid_back_over_is_drawn_again(tmp_path, monkeypatch):
    """Teleprint slides its window back when the document shrinks, so a fold below a picture
    returns rows that had scrolled away. Letting the picture go for good left a blank hole."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path, rows=20)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    tall = ui.say(Text('\n'.join(f'line {i}' for i in range(20))), 'tool', fold=None)
    ui.paint()
    assert not ui.pics[next(iter(ui.pics))].shown        # pushed off the top by the tall block
    writes.clear()
    tall.collapse_at = 1
    ui.comp.toggle(tall)
    assert PLACED.findall(''.join(writes)), 'the rows came back and the picture did not'
    tty.close()


def test_a_picture_whose_block_leaves_the_document_is_forgotten(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    ui.comp.remove_block(ui.comp.blocks[next(iter(ui.pics))])
    ui.paint()
    assert ui.pics == {}
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


def test_a_folded_picture_has_its_drawing_taken_off(tmp_path, monkeypatch):
    "One row of block cannot claim eleven rows of screen, so the drawing comes off until it opens."
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    ui.show_pic(p)
    blk = ui.comp.blocks[next(iter(ui.pics))]
    writes.clear()
    ui.comp.toggle(blk)
    assert blk.collapsed
    assert f'\x1b_Ga=d,d=i,i={ui.pics[blk.id].id},p=1' in ''.join(writes)
    writes.clear()
    ui.comp.toggle(blk)
    assert PLACED.findall(''.join(writes))     # opened again, and drawn again
    tty.close()


def test_a_terminal_that_cannot_draw_gets_rows_of_nothing_and_a_path(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_KITTY', '0')
    blob = _painted(_png(600, 600), tmp_path)
    assert '\x1b_G' not in blob
    assert PLACEHOLDER not in blob
    assert 'saved  ' in blob


def test_only_the_first_few_pictures_of_a_turn_are_drawn(tmp_path, monkeypatch):
    "A wall of tall blocks is what makes a transcript hard to scroll back through."
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    for _ in range(MAX_IMG_DRAW + 2):
        ui.show_pic(save_media({'mime': 'image/png', 'data': _png(64, 64)}, tmp_path))
    assert len(ui.pics) == MAX_IMG_DRAW
    assert ''.join(writes).count('a=t,f=100') == MAX_IMG_DRAW
    tty.close()


def test_every_picture_is_saved_and_named_however_many_a_turn_made(tmp_path, monkeypatch):
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    png = _png(64, 64)
    _painted(png, tmp_path, media=[{'mime': 'image/png', 'data': png}] * 5)
    assert len(list((tmp_path/'media').glob('*.png'))) == 5


# -- a picture a tool wrote still has to reach the screen -------------------------------

from ramabana.testing import fake_agent
from ramabana.tools import mime_for


def test_a_picture_a_tool_wrote_reaches_the_frontend(tmp_path, monkeypatch, caps):
    """A tool result is text. The model is handed a path, and a frontend cannot draw a
    filename, so the bytes have to arrive by another route or nothing is ever shown."""
    from base64 import b64encode
    png = _png(64, 64)
    caps(_Caps(('text', 'image'), ('text',)))
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('shalya.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    agent, _ = fake_agent(replies=['done'])
    agent._drawn = []
    gi = image_tools(None, session=str(tmp_path), get_spec=lambda: None,
                     on_media=agent._drew)[0]
    out = gi('a bottle')
    assert not failed(out)
    assert [m['data'] for m in agent.last_media] == [png]
    assert agent.last_media[0]['mime'] == 'image/png'


def test_a_turn_does_not_inherit_the_previous_turns_pictures():
    agent, _ = fake_agent(replies=['one', 'two'])
    agent._drew(['/nonexistent/a.png'])
    agent.ask('draw something')
    assert agent.last_media == []


def test_a_recorded_file_that_has_gone_away_is_skipped_not_raised(tmp_path):
    agent, _ = fake_agent(replies=['done'])
    agent._drawn = [tmp_path/'vanished.png']
    assert agent.last_media == []


def test_a_saved_picture_is_named_by_its_mime_and_read_back_by_its_bytes(tmp_path):
    "The extension comes from the mime, and the mime comes back from the bytes."
    png = _png(8, 8)
    p = save_media({'mime': 'image/png', 'data': png}, tmp_path)
    assert p.suffix == '.png' and mime_for(p) == 'image/png'
    assert save_media({'mime': 'video/mp4', 'data': b'x'}, tmp_path).suffix == '.mp4'
    assert save_media({'mime': 'image/webp', 'data': b'x'}, tmp_path).suffix == '.webp'


def test_the_mime_of_a_file_with_no_signature_falls_back_to_its_name(tmp_path):
    p = tmp_path/'a.webp'
    p.write_bytes(b'RIFF\x00\x00\x00\x00WEBPVP8 ')
    assert mime_for(p) == 'image/webp'
    assert mime_for(tmp_path/'missing.png') == 'image/png'

from ramabana.testing import FakeBackend


def _be(ctx=128_000):
    "A backend with no chat behind it, which is the shape every fit check is made in."
    return FakeBackend(ModelSpec('m', 'remote', 'm', ctx))


def test_image_bytes_in_a_pending_message_are_not_charged_as_their_own_repr():
    be = _be()
    assert be.pending_tokens([os.urandom(120_000), 'what is this?']) < 5_000


def test_the_fit_check_admits_a_screenshot_that_leaves_the_window_room():
    assert _be().fits([os.urandom(1_200_000), 'describe this'])


def test_the_text_beside_a_picture_is_still_measured():
    assert not _be().fits([os.urandom(1_000), 'x' * 600_000])


def test_a_picture_costs_the_same_however_the_caller_shaped_it():
    """Raw bytes and already-built content parts are the same picture.

    `_parts` only knew bytes and paths, so a caller that had already run its message through
    `mk_oai_content` handed over a dict, which was stringified -- base64 and all -- and charged as
    text. The repr bug again, one shape along.
    """
    from rishi.core import mk_oai_msg
    be, img = _be(), b'\x89PNG\r\n\x1a\n' + bytes(120_000)
    assert be.pending_tokens(mk_oai_msg([img, 'what is this?'])['content']) == \
           be.pending_tokens([img, 'what is this?'])


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
        agent = Agent(MemHost({'/proj/a.py': 'x = 1\n'}), extensions=False, subagents=False)
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


def test_the_reply_keeps_growing_below_every_picture(tmp_path, monkeypatch):
    "Same rule as a tool call: whatever the model says next belongs at the bottom of the screen."
    ui, blob, said = _drawing_turn(tmp_path, monkeypatch)
    tags = [b.tag for b in ui.comp.blocks.values()]
    assert tags.index('media') < len(tags) - 1 - tags[::-1].index('reply')


def test_the_hook_never_touches_the_surface_on_the_models_own_thread(tmp_path, monkeypatch):
    """`_drew` fires on the model's worker thread and a compositor may only be touched from the
    loop, so the whole of `show_pic` has to go through `_post`."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    ui, tty, writes = _surface(tmp_path)
    posted = []
    ui._post = lambda fn, *a: posted.append((fn, a))
    p = save_media({'mime': 'image/png', 'data': _png(600, 600)}, tmp_path)
    writes.clear()
    ui.agent._drew([p])                      # exactly as a tool does, from the tool's thread
    assert writes == [] and ui.pics == {}    # nothing reached the terminal yet
    assert len(posted) == 1
    posted[0][0](*posted[0][1])              # ...and running it on the loop draws it
    assert PLACED.findall(''.join(writes))
    tty.close()


def test_the_draw_quota_is_per_turn_and_not_per_session(tmp_path, monkeypatch):
    "Two turns each drawing one picture: the second turn must not inherit the first turn's count."
    ui, blob, said = _drawing_turn(tmp_path, monkeypatch, turns=2)
    assert ui.drawn == 1
    assert len(said) == 2
    assert blob.count('a=t,f=100') == 2


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


def test_a_turn_model_change_rebuilds_the_tools_even_when_the_budget_is_the_same():
    "`budget_for` gives every large-window model the same `Budget`, so budget alone is not the test."
    from ramabana.core import budget_for
    from ramabana.testing import fake_agent

    one, two = _spec('openai/gpt-5.6-luna'), _spec('anthropic/claude-opus-4-5')
    assert budget_for(one, 6000) == budget_for(two, 6000), 'the budgets differ, so this proves nothing'

    a, _ = fake_agent()
    a.routing.turn = one.name
    a.routing._cache[one.name], a.routing._cache[two.name] = one, two
    assert a.tools and a._tools is not None
    a.set_model(two.name)
    assert a._tools is None, 'the tools were kept across a turn-model change'
