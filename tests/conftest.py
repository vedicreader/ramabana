"""Fixtures for the suite.

The suite is one file per functional block, named for what it covers: routing, the context window,
the tools and the sandbox, the briefing, the approval gate, one turn, skills, extensions, the vault,
the trolley. There is no general `test_harness.py` any more, because it was where a block went when
nobody decided which block it was -- routing was hiding in it, and so was compaction.

Two tiers, and this is the second. The notebooks in `nbs/` carry a `## Tests` section each, written
to be read: they print what they checked, and they are the documentation. These are written to be
run in bulk, and each one names one contract so a failure says which behaviour broke.

Nothing here loads a model. What the harness is about is routing, approval, compaction arithmetic,
skill discovery, the activity stream and the tool wrappers, and a real engine would put gigabytes
and minutes in front of all of it while testing none of it.
"""

import pytest

from ramabana.testing import SPEC


@pytest.fixture
def spec(): return SPEC
