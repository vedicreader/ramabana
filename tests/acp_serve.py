"""An ACP agent on stdio with a scripted model, so a test can drive the real wire protocol.

`tests/test_acp.py` spawns this. `ACP_SCRIPT` picks what the model decides to do; the host,
the tools, the approval gate and the protocol are all real.
"""
import asyncio, os, pathlib
from ramabana.acp import AcpAgent, mk_agent, serve
from ramabana.testing import SCRIPTED, ScriptedBackend, Step

ROOT = pathlib.Path(os.environ['ACP_ROOT'])

class Gated(ScriptedBackend):
    "A scripted backend that puts its tool steps through the approval gate, as a real one does."
    def _tool(self, name):
        f = super()._tool(name)
        if f is None: return None
        def go(**kw):
            if self.approve is None: return f(**kw)
            a = self.approve({'function': {'name': name, 'arguments': kw}})
            if not a: return getattr(a, 'reply', lambda: 'refused')() or 'refused'
            return f(**kw)
        return go

SCRIPTS = {
    'edit': [Step(text='Looking at it now. '),
             Step(tool=('view_file', {'path': str(ROOT/'a.py')})),
             Step(tool=('create_file', {'path': str(ROOT/'b.py'), 'text': 'B = 1\n'})),
             Step(tool=('create_file', {'path': str(ROOT/'c.py'), 'text': 'C = 2\n'})),
             Step(text='Done: **b.py** now holds `B`.')],
    'view': [Step(tool=('view_file', {'path': str(ROOT/'a.py')})),
             Step(text='read it.')],
    'marker': [Step(tool=('run_shell', {'command': f'echo hi > {ROOT/"marker.txt"}'})),
                Step(text='ran it.')],
    'shell': [Step(text='Running the tests. '),
              Step(tool=('run_shell', {'command': 'echo hello'})),
              Step(text='They pass.')],
}

def mk(roots, **kw):
    "Stands in for `ramabana.acp.mk_agent`: a real host and gate, a scripted model."
    kw.pop('model', None)
    a, h = mk_agent(roots, model=None, web=False, vault=False, timeout=30,
                   cfg=ROOT/'.cfg', on_activity=kw.get('on_activity'))
    a.routing.turn, a.routing.policy = SCRIPTED.name, {}
    a.routing._cache[SCRIPTED.name] = SCRIPTED
    steps = SCRIPTS[os.environ.get('ACP_SCRIPT', 'edit')]
    be = Gated(SCRIPTED, steps=list(steps), token_delay=0, tools=a.tools, approve=a.approvals.gate)
    a._be = a._be_or_none = lambda job='turn': be
    return a, h

if __name__ == '__main__': asyncio.run(serve(AcpAgent(mk=mk, timeout=30)))
