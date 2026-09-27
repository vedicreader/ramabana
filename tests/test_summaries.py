"""Every tool an agent is given says what it just did, in words a person reads.

The mark is shalya's and lives beside each tool's docstring. Ramabana's share of it is its own
tools: delegation, the folder watches, the plan and the trolley. What is worth asserting here is
the whole surface at once, because the fault this replaced was silent. A tool with no summary
rendered as `git_status(path='/proj')` in the activity feed, beside `Search frontmatter`, and
nothing failed.

The four background delegation tools are the reason it is asserted rather than reviewed: they were
added to this repository and their summaries were forgotten in the same change.
"""
from ramabana.testing import FullHost, fake_agent
from ramabana.tools import Background, subagent_tools, tools_for

RAMABANA_OWN = ['delegate_search', 'delegate_parallel', 'delegate_async', 'delegate_status',
                'delegate_result', 'delegate_cancel', 'watch_folder', 'list_folder_watches',
                'cancel_folder_watch', 'check_folders', 'set_plan', 'add_todo', 'update_todo',
                'list_plan', 'cart_stores', 'cart_open', 'cart_find', 'cart_add', 'cart_show',
                'cart_remove']


def every_tool():
    """One of every tool a fully capable agent can be given, its own and the toolset's.

    The trolley is an extension rather than a host group, so it is built by hand here; nothing
    else reaches it, and a summary it never got is exactly what this file is for.
    """
    from ramabana.shop import Cart, cart_tools
    out = list(tools_for(FullHost()))
    out += list(subagent_tools(lambda: None, lambda: [], None, None, background=Background()))
    out += list(cart_tools(Cart()))
    a, _ = fake_agent()
    out += [t for t in a.tools if t.__name__ not in {x.__name__ for x in out}]
    return out


def test_every_tool_an_agent_is_given_carries_a_summary():
    bare = sorted({t.__name__ for t in every_tool() if getattr(t, 'summary', None) is None})
    assert bare == [], f'no summary on: {bare}'


def test_a_recorded_call_carries_the_summary_through_a_real_turn():
    a, _ = fake_agent()
    look = next(t for t in a.tools if t.__name__ == 'search_code')
    look(query='frontmatter')
    assert a.activity.acts[-1].summary == 'Search frontmatter'
