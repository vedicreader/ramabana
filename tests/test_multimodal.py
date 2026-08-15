"Audio reaching a model that can hear it, and pictures a model sent back."

import os
import struct
import zlib
from pathlib import Path

import pytest
from rich.text import Text

from ramabana.cli import (Attachment, draw_png, img_cells, kitty_graphics, media_line,
                          media_parts, media_note, png_size, save_media, sendable)
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
    assert draw_png(p) == ('', '')
    assert media_line(p).startswith('saved  ')
    assert '\x1b' not in media_line(p)


def test_a_non_png_is_saved_but_never_drawn(tmp_path, monkeypatch):
    "kittytgp is PNG-only, so a webp takes the path route even in a kitty terminal."
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = save_media({'mime': 'image/webp', 'data': b'RIFFwebp'}, tmp_path)
    assert p.suffix == '.webp' and p.exists()
    assert draw_png(p) == ('', '')


def test_a_truncated_png_is_refused_rather_than_measured(tmp_path, monkeypatch):
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = save_media({'mime': 'image/png', 'data': b'not a png at all'}, tmp_path)
    assert png_size(p) is None
    assert draw_png(p) == ('', '')


def test_a_picture_is_measured_from_its_header_and_fitted_to_the_width(tmp_path):
    p = tmp_path/'a.png'
    p.write_bytes(_png(1254, 1254))
    assert png_size(p) == (1254, 1254)
    assert img_cells(p, 80) == (60, 29)      # clamped to MAX_IMG_COLS, square on screen
    assert img_cells(p, 20) == (20, 10)
    assert img_cells(tmp_path/'wide.png', 40) is None


def test_the_transmit_never_reaches_the_transcript(tmp_path, monkeypatch):
    """`rich` strips the APC introducer but keeps its payload, so a transmit sent as text spills
    a megabyte of base64 onto the screen. The two halves come back separately for that reason."""
    pytest.importorskip('kittytgp')
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = tmp_path/'a.png'
    p.write_bytes(_png(64, 64))
    tx, cells = draw_png(p, 40)
    assert tx.startswith('\x1b_G') and tx.endswith('\x1b\\')
    assert '\x1b_G' not in cells and 'iVBOR' not in cells
    assert cells.count(PLACEHOLDER) > 0
    assert Text.from_ansi(cells).plain.count(PLACEHOLDER) == cells.count(PLACEHOLDER)


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
    monkeypatch.setattr('ramabana.tools._post_image', lambda *a, **kw: called.append(a))
    assert failed(_gi()('a cat', size='4096x4096'))
    assert called == []


def test_a_generated_picture_lands_beside_the_session(tmp_path, monkeypatch):
    from base64 import b64encode
    png = b'\x89PNG\r\n\x1a\nx'
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('ramabana.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    out = _gi(session=str(tmp_path))('a cat')
    assert not failed(out)
    p = Path(out.strip())
    assert p.parent == tmp_path/'media' and p.read_bytes() == png


def test_an_endpoint_failure_is_a_refusal_not_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    def boom(*a, **kw): raise RuntimeError('502 upstream')
    monkeypatch.setattr('ramabana.tools._post_image', boom)
    r = _gi(session=str(tmp_path))('a cat')
    assert failed(r) and '502 upstream' in r


def test_an_empty_reply_is_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('ramabana.tools._post_image', lambda *a, **kw: [])
    assert failed(_gi(session=str(tmp_path))('a cat'))


def test_the_tool_is_registered_only_where_the_key_is(monkeypatch):
    h = MemHost({'/proj/a.py': 'x = 1'})
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    assert 'generate_image' in [f.__name__ for f in tools_for(h)]
    assert 'generate_image' not in [f.__name__ for f in tools_for(h, drop={'image'})]
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert 'generate_image' not in [f.__name__ for f in tools_for(h)]
