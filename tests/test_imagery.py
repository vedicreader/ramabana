"The imagery extension, the packaged skills it pairs with, and the tool that lets an agent look."
from base64 import b64decode
from pathlib import Path

import pytest

from ramabana.testing import MemHost
from ramabana.tools import Registry, discover, load, look_tools, tools_for

EXT = Path(__file__).parent.parent/'extensions'/'imagery.py'
#: a real 4x4 png, so the look path can decode it whether or not Pillow is installed
PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFElEQVR4nGM8IafBAANMDEgANwcANmABFlbv'
                '7IsAAAAASUVORK5CYII=')


def _reg():
    reg = Registry()
    load(reg, paths=[EXT])
    return reg


def _png(dir, name='x.png'):
    p = Path(dir)/name
    p.write_bytes(PNG)
    return p


def test_the_extension_says_what_it_found_and_never_raises():
    reg = _reg()
    assert reg.notes, 'the extension has to report what it loaded'
    for note in reg.notes: assert 'Traceback' not in note


def test_chitra_tools_reach_the_registry_when_chitra_is_installed():
    pytest.importorskip('chitra')
    names = {f.__name__ for f in _reg().tools}
    assert {'filter_region', 'measure_masks', 'views_needed'} <= names


def test_anya_tools_reach_the_registry_when_anya_is_installed():
    pytest.importorskip('anya')
    names = {f.__name__ for f in _reg().tools}
    assert {'segment_masks', 'classify_image'} <= names
    assert 'sort_folder' not in names, "a tool that moves a user's files is not registered here"


def test_a_packaged_skill_md_is_discovered_through_its_entry_point():
    pytest.importorskip('chitra')
    found = {s.name: s for s in discover()}
    assert 'chitra' in found
    s = found['chitra']
    assert s.source == 'pyskill' and s.where == 'chitra:SKILL.md'
    assert 'mask' in s.text().lower() and s.description


def test_look_at_is_in_the_default_tool_set():
    assert 'look_at' in {f.__name__ for f in tools_for(MemHost())}


def test_look_at_says_so_when_nothing_in_the_session_can_see(tmp_path):
    out = look_tools(MemHost())[0](str(_png(tmp_path)))
    assert 'looked at it' in out


def test_look_at_hands_the_bytes_to_the_looker_and_the_path_to_the_screen(tmp_path):
    shown = []
    tool = look_tools(MemHost(), on_media=shown.append,
                      look=lambda data, q: f'{len(data)} bytes for {q!r}')[0]
    out = tool(str(_png(tmp_path)), 'where is the car')
    assert 'where is the car' in out and 'bytes' in out
    assert len(shown) == 1


def test_look_at_refuses_what_is_not_a_picture(tmp_path):
    p = Path(tmp_path)/'x.txt'
    p.write_text('hello')
    assert 'not a picture' in look_tools(MemHost())[0](str(p))


def test_look_at_reports_a_failing_looker_rather_than_raising(tmp_path):
    def boom(data, q): raise RuntimeError('no vision here')
    out = look_tools(MemHost(), look=boom)[0](str(_png(tmp_path)))
    assert 'could not look at it' in out and 'no vision here' in out
