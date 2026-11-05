"""Focus blocks: `/pomo [minutes]` counts a focus block down, then runs a 5-minute break.

`/pomo` shows what is left and `/pomo stop` ends the block early. During a break, new prompts are refused with the minutes left. To send one anyway, start the prompt with `!`.

The running block is kept in the mod's store, so `/reload` carries it on with the time that is left.
"""
import math, time

now = time.time
BREAK_SECONDS, DEFAULT_MINUTES, MAX_MINUTES = 5 * 60, 25, 120


def setup(reg):
    state = dict(gen=0, mode=None, end=0.0, timers=[])
    store = reg.store(dict(mode=None, end=0.0))

    def persist(): store.update(lambda data: data.update(mode=state['mode'], end=state['end']))

    def left(end): return math.ceil((end - now()) / 60)

    def schedule(seconds, fn):
        gen = state['gen']

        def run():
            if gen == state['gen']: fn()
        state['timers'].append(reg.after(seconds, run))

    def cancel():
        for handle in state['timers']: handle.cancel()
        state.update(gen=state['gen'] + 1, mode=None, timers=[])
        persist()

    def block_done():
        state.update(mode='break', end=now() + BREAK_SECONDS, timers=[])
        schedule(BREAK_SECONDS, break_over)
        persist()
        reg.notify('Pomodoro done. Take a 5-minute break.')

    def break_over():
        state.update(mode=None, timers=[])
        persist()
        reg.notify('Break over.')

    def status(agent):
        if state['mode'] is None: return None
        return f"{state['mode']} {left(state['end'])}m"

    def gate(agent, prompt):
        if state['mode'] != 'break' or prompt.startswith('!'): return None
        return f"pomodoro: on a break, {left(state['end'])} min left"

    def pomo(agent, arg):
        arg = arg.strip()
        if arg == 'stop':
            if state['mode'] is None: return 'No block running.'
            cancel()
            return 'Stopped.'
        if state['mode'] is not None:
            if arg: return 'A block is already running. /pomo stop ends it first.'
            return f"{state['mode']}: {left(state['end'])} min left."
        minutes = DEFAULT_MINUTES
        if arg:
            if not arg.isdigit() or not 1 <= int(arg) <= MAX_MINUTES:
                return f'Usage: /pomo [minutes], from 1 to {MAX_MINUTES}; /pomo stop; /pomo.'
            minutes = int(arg)
        state.update(mode='pomo', end=now() + minutes * 60, timers=[])
        schedule(minutes * 60, block_done)
        persist()
        reg.redraw()
        return f'Focus block started: {minutes} min.'

    if store.data['mode'] is not None and store.data['end'] > now():
        state.update(mode=store.data['mode'], end=store.data['end'])
        schedule(state['end'] - now(), block_done if state['mode'] == 'pomo' else break_over)
    reg.status(status)
    reg.on('before_turn', gate)
    reg.command('pomo', pomo, 'focus block: /pomo [minutes], /pomo stop')
    reg.every(60, reg.redraw)
