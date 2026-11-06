r"""A side-pane log of the decisions the person has made and the ones still waiting for them, kept for each session, with items on hold kept for each folder."""
import re, time

USAGE = r'Usage: /decide [? QUESTION | DECISION | done N [CHOICE] | undo N | edit N TEXT | park N UNTIL | resume hN | drop N | clear]'
RECENT = 20
GUIDE = (r'When you put a choice to the person, call `decision` with action `ask`. '
         r'When the person or you settle a choice, call `decision` with action `record` and the choice. '
         r'When a question must wait for something else, or the work for a decision is put off while another issue is solved, call `park` with its number and the condition in `text`. '
         r'Items on hold are numbered h1, h2 and stay for every session in this folder. Do not act on one; call `resume` with its h number when its condition is met. '
         r'Entry numbers never change. To fix an entry, call `edit`, `reopen` or `drop` with its number.')
VERBS = dict(done='done', undo='reopen', reopen='reopen', edit='edit', park='park', resume='resume', drop='drop')   #: `/decide` verbs and the `fix` action each runs
HIDDEN = ('dropped', 'held')   #: states no section shows; `held` marks a session entry moved to the folder's list
REF = re.compile(r'h?\d+', re.I)
STYLES = {'Needs your decision': 'yellow', 'Decide later': 'aqua', 'Build later': 'blue', 'Decided': 'green'}   #: the pane colour of each section's rows


def find(items, ref, state=None):
    "The index of the item in `state` (any shown state when None) that `ref` names by number, exact text or unique substring, ignoring case; else None."
    ref = ref.strip()
    if not ref: return None
    if ref.isdecimal():
        i = int(ref) - 1
        return i if 0 <= i < len(items) and items[i]['state'] not in HIDDEN and state in (None, items[i]['state']) else None
    low = ref.lower()
    cands = [i for i, d in enumerate(items) if d['state'] not in HIDDEN and state in (None, d['state'])]
    for pred in (lambda t: t == low, lambda t: low in t):
        if len(hits := [i for i in cands if pred(items[i]['text'].lower())]) == 1: return hits[0]
    return None


def label(d): return d['text'] + (f" -> {d['choice']}" if d['choice'] else '')


def age(at, now):
    "How long ago `at` was, as '2h' or '3d'; '' under an hour."
    s = now - at
    return '' if s < 3600 else f'{int(s // 86400)}d' if s >= 86400 else f'{int(s // 3600)}h'


def rows(items, state, now=None):
    "The numbered rows of this session's items in `state`; an open one older than an hour shows its age."
    now = time.time() if now is None else now
    return [f'{n}. {label(d)}' + (f' · {a}' if state == 'open' and (a := age(d.get('at', now), now)) else '')
            for n, d in enumerate(items, 1) if d['state'] == state]


def held_rows(held, state):
    "The numbered rows of this folder's items on hold in `state`, each with its condition."
    return [f"h{n}. {label(d)} · until {d['until']}" for n, d in enumerate(held, 1) if d['state'] == state]


def sections(its, held):
    "Each section's title and rows, in the order the pane shows them."
    return [('Needs your decision', rows(its, 'open')), ('Decide later', held_rows(held, 'open')),
            ('Build later', held_rows(held, 'decided')), ('Decided', rows(its, 'decided'))]


def listing(its, held):
    "Every nonempty section as text, or '' when all are empty."
    return '\n\n'.join(f'{title}:\n' + '\n'.join(r) for title, r in sections(its, held) if r)


def ask(items, text):
    "Add `text` as an open question unless one with that text is open; returns what to tell the caller."
    if any(d['state'] == 'open' and d['text'].lower() == text.lower() for d in items): return f'already open: {text}'
    items.append(dict(text=text, state='open', choice='', at=time.time()))
    return f'open {len(items)}: {text}'


def record(items, ref, choice=''):
    "Settle the open question `ref` names with `choice`, or log `ref` as a new decision when it is not a number and names no open question."
    if (i := find(items, ref, 'open')) is None:
        if ref.strip().isdecimal(): return f'no open question {ref.strip()}; open questions:\n' + '\n'.join(rows(items, 'open'))
        return log(items, ref.strip(), choice)
    items[i].update(state='decided', choice=choice.strip())
    return f'decided {i + 1}: {label(items[i])}'


def log(items, text, choice=''):
    "Add `text` as a decision already made, with `choice`; returns what to tell the caller."
    items.append(dict(text=text, state='decided', choice=choice.strip(), at=time.time()))
    return f'decided {len(items)}: {label(items[-1])}'


def fix(its, held, action, ref, text='', choice=''):
    "Apply `action` to the session entry `ref`, or to the held entry `hN`; returns the log, or why nothing changed."
    ref, text, choice = ref.strip().lower(), text.strip(), choice.strip()
    on_hold = ref.startswith('h')
    pool = held if on_hold else its
    if not REF.fullmatch(ref) or (i := find(pool, ref.lstrip('h'))) is None: return f'no item {ref}'
    d = pool[i]
    if action == 'edit':
        if not (text or choice): return 'nothing to edit: give the new text or choice'
        if choice and d['state'] == 'open': return f'{ref} is open; record it to give a choice'
        d.update({k: v for k, v in dict(text=text, choice=choice).items() if v})
    elif action == 'park':
        if not text: return f'give the condition {ref} waits until'
        if on_hold: d['until'] = text
        else: held.append(dict(d, until=text)); d['state'] = 'held'
    elif action == 'drop': d['state'] = 'dropped'   # kept in the file, so no later entry is renumbered
    elif on_hold:
        state = dict(resume=d['state'], done='decided', reopen='open')[action]
        its.append(dict(text=d['text'], state=state, at=d.get('at', time.time()),
                        choice=choice if action == 'done' else '' if state == 'open' else d['choice']))
        d['state'] = 'dropped'
    elif action == 'resume': return f'{ref} is not on hold'
    elif action == 'reopen' and d['state'] == 'open': return f'{ref} is already open'
    else: d.update(state='decided' if action == 'done' else 'open', choice=choice if action == 'done' else '')
    return listing(its, held) or 'no decisions left'


def setup(reg):
    store = reg.store(dict(sessions={}, folders={}))

    def folder(agent): return str(agent.host.roots[0]) if agent.host.roots else ''

    def items(agent, data=None):
        "This session's entries and this folder's held entries."
        data = store.data if data is None else data
        return data['sessions'].get(agent.session_id, []), data.get('folders', {}).get(folder(agent), [])

    def change(agent, fn):
        "Run `fn(its, held)` under the store's lock, save, redraw, and return what `fn` returns."
        out = []
        store.update(lambda data: out.append(fn(data['sessions'].setdefault(agent.session_id, []),
                                                data.setdefault('folders', {}).setdefault(folder(agent), []))))
        reg.redraw()
        return out[0]

    def command(agent, arg):
        its, held = items(agent, store.reload())
        if store.problem: return f'decisions: the saved log cannot be read: {store.problem}\nFix or delete {store.path}.'
        arg = arg.strip()
        verb, _, rest = arg.partition(' ')
        rest = rest.strip()
        if not arg: return listing(its, held) or 'no decisions yet; /decide ? QUESTION adds an open question'
        if arg.startswith('?'): return change(agent, lambda its, held: ask(its, arg[1:].strip())) if arg[1:].strip() else USAGE
        if arg == 'clear':
            def clear(its, held):
                done = [d for d in its if d['state'] == 'decided']
                for d in done: d['state'] = 'dropped'
                return f'cleared {len(done)} decision(s)'
            return change(agent, clear)
        n, _, tail = rest.partition(' ')
        if verb in VERBS and not rest: return USAGE
        if verb in VERBS and REF.fullmatch(n):
            action = VERBS[verb]
            return change(agent, lambda its, held: fix(its, held, action, n, choice=tail) if action == 'done' else fix(its, held, action, n, text=tail))
        return change(agent, lambda its, held: log(its, arg))

    def decision(
        action:str, # `ask` when you put a choice to the person, `record` when a choice is settled, `list` to read the log; `park` or `resume` to put an entry on hold or take it off; `edit`, `reopen` or `drop` to fix an entry
        question:str='', # the question, or an entry's number (h1, h2 for an entry on hold); for `record` with no open question, the decision itself
        choice:str='', # what was chosen, for `record`; the new choice of a decided entry, for `edit`
        text:str='', # the entry's new wording, for `edit`; for `park`, the condition alone, such as 'Leela 0.1.22 ships', which the pane shows after 'until'
    )->str:
        "Keep the person's decision log, shown in their side pane: log each choice you put to them and each choice they or you settle."
        agent = reg.agent
        if action == 'list': return listing(*items(agent)) or 'no decisions yet'
        if action == 'record' and re.fullmatch(r'h\d+', question.strip(), re.I): action = 'done'
        if action in ('done', 'edit', 'reopen', 'park', 'resume', 'drop'): return change(agent, lambda its, held: fix(its, held, action, question, text, choice))
        if action not in ('ask', 'record'): return f'unknown action {action!r}; use ask, record, list, park, resume, edit, reopen or drop'
        if not question.strip(): return f'nothing to {action}: question is empty'
        return change(agent, lambda its, held: ask(its, question.strip()) if action == 'ask' else record(its, question, choice))

    def before_turn(agent, prompt):
        its, held = items(agent)
        parts = [GUIDE]
        if (open_ := rows(its, 'open')): parts.append('Questions waiting for the person:\n' + '\n'.join(open_) + '\nIf the message settles one, record it.')
        if (done := rows(its, 'decided')): parts.append('Decisions made this session:\n' + '\n'.join(done[-RECENT:]))
        if (hold := held_rows(held, 'open') + held_rows(held, 'decided')): parts.append('On hold in this folder:\n' + '\n'.join(hold))
        return {'context': '\n\n'.join(parts)}

    def status(agent):
        n = len(rows(items(agent)[0], 'open'))
        return f'decide {n}' if n else None

    reg.tool(decision)
    reg.command('decide', command, 'Show or change the decision log.')
    reg.status(status)
    for i, (title, _) in enumerate(sections([], [])):
        reg.section(title, lambda agent, i=i: sections(*items(agent))[i][1], style=STYLES[title])
    reg.on('before_turn', before_turn)
