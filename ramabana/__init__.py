__version__ = "0.1.33"

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