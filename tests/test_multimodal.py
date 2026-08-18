"Audio reaching a model that can hear it, and pictures a model sent back."

import os
import struct
import zlib
from pathlib import Path

import pytest
from rich.text import Text

from ramabana.cli import (MAX_IMG_DRAW, Attachment, draw_png, img_cells, kitty_graphics,
                          media_line, media_parts, media_note, png_size, save_media, sendable)
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


def test_a_picture_is_a_direct_placement_and_never_a_placeholder(tmp_path, monkeypatch):
    """Placeholders are the tidier idea and these terminals ignore `U=1`, printing U+10EEEE as a
    missing glyph -- so every picture used to arrive with a block of tofu behind it."""
    monkeypatch.setenv('KITTY_WINDOW_ID', '1')
    p = tmp_path/'a.png'
    p.write_bytes(_png(600, 600))            # big enough that the payload must be chunked
    esc = draw_png(p, 40)
    assert esc.startswith('\x1b_G') and esc.endswith('\x1b\\')
    assert 'a=T' in esc and 'C=1' in esc and 'U=1' not in esc
    assert PLACEHOLDER not in esc
    # exactly one chunk says "no more"; every earlier one says there is
    assert esc.count('m=0') == 1
    assert esc.count('m=1') == esc.count('\x1b_G') - 1


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
    monkeypatch.setattr('ramabana.tools._post_responses', fake)
    monkeypatch.setattr('ramabana.tools._post_image', lambda *a, **kw: pytest.fail('delegated'))
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
    monkeypatch.setattr('ramabana.tools._post_responses', lambda *a, **kw: pytest.fail('should not ask'))
    monkeypatch.setattr('ramabana.tools._post_image',
                        lambda *a, **kw: [{'b64_json': b64encode(png).decode()}])
    gi = _gi(session=str(tmp_path), get_spec=lambda: _spec('anthropic/claude-opus-4-5'))
    assert Path(gi('a bottle').strip()).read_bytes() == png


def test_a_drawing_model_that_returns_no_picture_is_a_refusal(tmp_path, monkeypatch, caps):
    c = _Caps(('text', 'image'), ('text',)); c.tools = ('image',)
    caps(c)
    monkeypatch.setenv('OPENAI_API_KEY', 'k')
    monkeypatch.setattr('ramabana.tools._post_responses',
                        lambda *a, **kw: {'output': [{'type': 'message'}]})
    gi = _gi(session=str(tmp_path), get_spec=lambda: _spec('openai/gpt-5.6-luna'))
    assert failed(gi('a bottle'))


# -- the picture actually reaches the screen -------------------------------------------

def _painted(png_bytes, tmp_path, cols=100, rows=40, media=None):
    "Every byte the compositor and the out-of-band write put on an emulated tty."
    import asyncio
    from teleprint.compositor import Compositor
    from teleprint.testing import EmuTty
    from ramabana.cli import Ui
    from ramabana.testing import fake_agent

    async def run():
        tty = EmuTty(cols, rows)
        comp = Compositor(tty); comp._register_signals = lambda: None
        await comp.start()
        agent, _ = fake_agent(replies=['ok'])
        ui, writes = Ui(comp, agent), []
        orig = tty.write
        tty.write = lambda s: (writes.append(s), orig(s))[1]
        ui.show_media(media or [{'mime': 'image/png', 'data': png_bytes}], session=str(tmp_path))
        ui.paint()
        return ''.join(writes)
    return asyncio.run(run())


def test_nothing_is_drawn_into_the_transcript_and_no_glyphs_reach_it(tmp_path, monkeypatch):
    """Inline drawing is off. A placement lands at the cursor, which after a paint is the input
    line, and the next frame erases it -- a blank gap where a picture should be."""
    monkeypatch.setenv('RAMABANA_KITTY', '1')
    blob = _painted(_png(600, 600), tmp_path)
    assert '\x1b_G' not in blob          # no image escape...
    assert PLACEHOLDER not in blob       # ...and no placeholder glyphs either


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
    monkeypatch.setattr('ramabana.tools._post_image',
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
