"""Skill discovery: what the agent finds, what wins when two things claim a name, and how much of
it reaches the briefing.

The test of whether this is a real feature rather than an architectural one is that installing a
package which publishes the entry point hands the agent its skill, with no code here.
"""
from ramabana import tools


def test_skills_are_discovered_from_installed_packages_and_overridden_by_files(tmp_path):
    """A pyskill is a module whose docstring is the skill text, so it versions and installs like any
    other Python. A project's own `SKILL.md` beats one, deliberately: the precedence is file over
    package because the file is the one somebody in this repository wrote. A loose `.md` at the root
    is not a skill, and the frontmatter parses without a YAML dependency.
    """
    found = {s.name: s for s in tools.discover()}
    assert 'exhash' in found, 'exhash ships the editing reference leela used to paste by hand'
    assert found['exhash'].source == 'pyskill' and found['exhash'].text().strip()

    patterns = found['coding_patterns']
    assert patterns.source == 'pyskill' and patterns.where == 'ramabana.coding_patterns'
    assert 'Every construct must earn its place' in patterns.text()
    assert 'Ramabana workflow' in patterns.text()

    d = tmp_path/'skills'/'exhash'
    d.mkdir(parents=True)
    (d/'SKILL.md').write_text('---\nname: exhash\ndescription: ours\n---\n\nlocal body\n')
    (tmp_path/'skills'/'loose.md').write_text('not a skill')
    over = {s.name: s for s in tools.discover(cfg=tmp_path)}
    assert over['exhash'].source == 'md' and over['exhash'].description == 'ours'
    assert 'local body' in over['exhash'].text()
    assert 'loose' not in over

    meta, body = tools.frontmatter('---\nname: x\ndescription: "y z"\n---\nbody\n')
    assert meta == {'name': 'x', 'description': 'y z'} and body.strip() == 'body'


def test_the_index_carries_names_not_bodies_and_find_refuses_to_guess():
    """Progressive disclosure: a dozen full skill texts would crowd out the code being worked on.
    The total scales with how many skills happen to be installed, so the invariant that holds is
    per row -- a name and one clipped line, never a body. `hf-cli` ships a 1000-char frontmatter
    description, and without the clip one skill crowds out the rest.
    """
    from ramabana.tools import Skill, find
    ss = tools.discover()
    idx = tools.skill_index(ss)
    assert 'read_skill' in idx
    for s in ss: assert s.name in idx
    rows = [l for l in idx.splitlines() if l.startswith('- `')]
    assert len(rows) == len(ss)
    for r in rows: assert len(r) <= tools.SKILL_DESC_MAX + max(len(s.name) for s in ss) + 8

    two = [Skill('editskill', 'pyskill'), Skill('editor', 'pyskill')]
    assert find(two, 'edit') is None                    # ambiguous: never guess
    assert find(two, 'editskill').name == 'editskill'
