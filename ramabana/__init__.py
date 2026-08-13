"""rama's arrow. a harness that does not miss

Modules:

- `ramabana.agent`: The turn: what the model is told, what it is allowed to do, what it did, and what that cost.
- `ramabana.coding_patterns`: Answer.AI coding standards adapted to Ramabana's tools and nbdev workflow.
- `ramabana.mcp`: Ramabana's tools, and Ramabana's whole agent, as an MCP server.
- `ramabana.runtime`: Everything that runs a model: native output capture, the context window, and the backend the harness talks to.
- `ramabana.shop`: A trolley the agent can fill: `fossick.shop` behind a small interface, and the weekly grocery run it was written for.
- `ramabana.testing`: The doubles: a host with no disk, backends with no model, and a script that behaves like a bad local engine.
- `ramabana.tools`: The hands: what the application under the agent must provide, and every tool built on top of it.
- `ramabana.vault`: Memory that outlives the process: one vishalakshi vault behind `Host`, and the standing watches that put things back on the agent's desk."""

__version__ = "0.1.1"

from .core import AgentError, agent_err, env

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask',
           'Plan', 'Todo', 'ModelSpec', 'Routing', 'AgentError', 'agent_err', 'env']

_lazy = {'Host': ('.tools', 'Host'), 'NullHost': ('.tools', 'NullHost'), 'Hit': ('.tools', 'Hit'),
         'Backend': ('.runtime', 'Backend'), 'Agent': ('.agent', 'Agent'),
         'Completer': ('.agent', 'Completer'), 'Approvals': ('.agent', 'Approvals'),
         'Ask': ('.agent', 'Ask'), 'Plan': ('.agent', 'Plan'), 'Todo': ('.agent', 'Todo'),
         'ModelSpec': ('.core', 'ModelSpec'), 'Routing': ('.core', 'Routing')}


def __getattr__(name):
    """Import the heavy names on first touch.

    `runtime` reaches for Rishi, which lazily loads the selected local or hosted engine;
    it should not be imported because someone merely asked for `ramabana.Host`.
    """
    if name in _lazy:
        from importlib import import_module
        mod, attr = _lazy[name]
        return getattr(import_module(mod, __name__), attr)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

def __dir__(): return sorted(list(globals()) + list(_lazy))
