"""ramabana: the brain of a coding agent, and nothing else.

The application around it supplies hands, through the `Host` protocol in `host.py`; the
model arrives through rishi. Nothing in here knows what an editor is, which is what makes
it possible to host one somewhere that is not leela.

Read `host.py` first. It is the entire dependency this package has on the world, and the
docstrings in it are the specification -- a host that satisfies the signatures and not the
contracts is a host that quietly hands an agent the whole filesystem.
"""

__version__ = "0.0.1"

from .core import AgentError, agent_err, env

__all__ = ['Host', 'NullHost', 'Hit', 'Backend', 'Agent', 'Completer', 'Approvals', 'Ask',
           'ModelSpec', 'Routing', 'AgentError', 'agent_err', 'env']

_lazy = {'Host': ('.host', 'Host'), 'NullHost': ('.host', 'NullHost'), 'Hit': ('.host', 'Hit'),
         'Backend': ('.backend', 'Backend'), 'Agent': ('.chat', 'Agent'),
         'Completer': ('.chat', 'Completer'), 'Approvals': ('.hitl', 'Approvals'),
         'Ask': ('.hitl', 'Ask'), 'ModelSpec': ('.models', 'ModelSpec'),
         'Routing': ('.models', 'Routing')}


def __getattr__(name):
    """Import the heavy names on first touch.

    `backend` reaches for rishi (a multi-gigabyte local engine) and fastllm (which pulls a
    provider stack); neither should be imported because someone asked for `ramabana.Host`.
    """
    if name in _lazy:
        from importlib import import_module
        mod, attr = _lazy[name]
        return getattr(import_module(mod, __name__), attr)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__(): return sorted(list(globals()) + list(_lazy))
