"""Give an agent the image toolkits: anya's models and chitra's editing tools.

Copy this file into `<config>/extensions/`, or into a project's `.leela/extensions/`, and the tools
appear on the next turn. Whichever package is not installed is noted and skipped, so this file is
safe to leave in place on a machine that has neither.

    pip install anya[onnx] chitra

anya says where things are, chitra changes the pixels, and both report numbers rather than opinions.
`/extensions` lists what loaded.
"""
from importlib import import_module

#: what to take from each package. anya's `sort_folder` moves a user's files, so it stays out
WANT = (('anya.tools', ('SAFE', 'segment_masks')),
        ('chitra.tools', ('TOOLS',)))


def _tools(mod, names):
    "The named tool lists and single tools out of one module, flattened."
    m = import_module(mod)
    out = []
    for n in names:
        o = getattr(m, n)
        out += list(o) if isinstance(o, (list, tuple)) else [o]
    return out


def setup(reg):
    "Register every tool the image packages publish, and say what was missing."
    for mod, names in WANT:
        try: fns = _tools(mod, names)
        except ImportError as e:
            reg.notes.append(f'{mod}: not installed ({e})')
            continue
        except Exception as e:
            reg.notes.append(f'{mod}: {type(e).__name__}: {e}')
            continue
        for f in fns: reg.tool(f)
        reg.notes.append(f'{mod}: {len(fns)} tools')
