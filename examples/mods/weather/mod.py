"""Context and tool-use forecast for the session.

A status segment reads context fullness as a word: clear under 50 percent, cloudy up to 80, storm above. The agent reports fullness as a fraction from 0 to 1; a larger value counts as full. A band above the prompt draws a sparkline of tool calls over the last 20 turns, red where a turn had failed calls. `/weather` prints a short report.
"""
from collections import deque

HISTORY = 20
SPARKS = '▁▂▃▄▅▆▇█'


def _pct(agent):
    try: return min(float(agent.status()['pct_full']), 1.0)
    except (AttributeError, KeyError, TypeError, ValueError): return None


def setup(reg):
    turns = deque(maxlen=HISTORY)
    tally = dict(calls=0, failures=0, seen=0)

    def after_tool(agent, name, out):
        tally['calls'] += 1
        if isinstance(out, str) and out.startswith('ERROR'): tally['failures'] += 1

    def after_turn(agent, text):
        turns.append((tally['calls'], tally['failures']))
        tally.update(calls=0, failures=0, seen=tally['seen'] + 1)

    def status(agent):
        pct = _pct(agent)
        if pct is None: return None
        word = 'clear' if pct < 0.5 else 'cloudy' if pct <= 0.8 else 'storm'
        return f'ctx {word} {round(pct * 100)}%'

    def band(view):
        label = 'tools '
        room = view.width - len(label)
        if view.busy or not turns or room < 1: return None
        peak = max(calls for calls, _ in turns) or 1
        row = [(label, 'dim')]
        for calls, failures in list(turns)[-room:]:
            row.append((SPARKS[round(7 * calls / peak)], 'red' if failures else '#6a9955'))
        return [row]

    def weather(agent, arg):
        if not turns: return 'No turns finished yet.'
        calls = sum(c for c, _ in turns)
        failures = sum(f for _, f in turns)
        return (f"Turns seen: {tally['seen']}. Average calls over the last {len(turns)}: "
                f'{calls / len(turns):.1f}. Failed calls: {failures}.')

    reg.on('after_tool', after_tool)
    reg.on('after_turn', after_turn)
    reg.status(status)
    reg.band(band, rows=2)
    reg.command('weather', weather, 'tool-use and context forecast')
