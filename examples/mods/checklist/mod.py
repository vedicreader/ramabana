r"""A sticky checklist the person pins: the agent sees the open items each turn, and gating items hold commits and pushes."""

from fastcore.xtras import Path

GATED = ('git_commit', 'git_remote')
MARKS = dict(open=' ', done='x', skipped='-')
USAGE = r'Usage: /check [add TEXT | add! TEXT | done N | skip N [REASON] | undo N | rm N | clear | suggest | pin K]'


def suggestions(learned):
    "The `- ` items of `<learned>/checklist.md`, or None when learning is off."
    if learned is None: return None
    f = Path(learned)/'checklist.md'
    if not f.exists(): return []
    return [t for line in f.read_text().splitlines() if line.startswith('- ') and (t := line[2:].strip())]


def render(items):
    "Numbered rows with a mark: `[ ]` open, `[x]` done, `[-]` skipped; `!` flags a gating item."
    return '\n'.join(f'{i}. [{MARKS[it["state"]]}]{"!" if it["gate"] else ""} {it["text"]}' + (f' ({it["reason"]})' if it['reason'] else '')
                     for i, it in enumerate(items, 1))


def find(items, ref, states=MARKS):
    "The index of the item in `states` that `ref` names by number, exact text or unique substring, ignoring case; else None."
    ref = ref.strip()
    if not ref: return None
    if ref.isdecimal():
        i = int(ref) - 1
        return i if 0 <= i < len(items) and items[i]['state'] in states else None
    low = ref.lower()
    cands = [i for i, it in enumerate(items) if it['state'] in states]
    for pred in (lambda t: t == low, lambda t: low in t):
        if len(hits := [i for i in cands if pred(items[i]['text'].lower())]) == 1: return hits[0]
    return None


def add(items, text, gate=False):
    "Pin `text` as an open item, or make the open item with that text gating; returns what to tell the caller."
    if (old := next((it for it in items if it['state'] == 'open' and it['text'].lower() == text.lower()), None)):
        if not gate or old['gate']: return f'already pinned: {text}'
        old['gate'] = True
        return f'now gating: {text}'
    items.append(dict(text=text, state='open', gate=gate, reason=''))
    return f'added {len(items)}: {text}' + (' (gates git_commit and git_remote pushes)' if gate else '')


def setup(reg):
    store = reg.store(dict(items=[]))

    def change(fn):
        "Run `fn(items)` under the store's lock, save, and return what `fn` returns."
        out = []
        store.update(lambda data: out.append(fn(data['items'])))
        return out[0]

    def command(agent, arg):
        items = store.reload()['items']
        if store.problem: return f'checklist: the saved list cannot be read: {store.problem}\nFix or delete {store.path}.'
        verb, _, rest = arg.strip().partition(' ')
        rest = rest.strip()
        if not verb: return render(items) or 'checklist is empty; /check add TEXT pins an item'
        if verb in ('add', 'add!') and rest: return change(lambda its: add(its, rest, verb == 'add!'))
        if verb in ('suggest', 'pin'):
            found = suggestions(getattr(agent, 'learned_dir', None))
            if found is None: return 'learning is off, so there are no suggestions'
            if verb == 'suggest': return '\n'.join(f'{k}. {t}' for k, t in enumerate(found, 1)) or 'no suggestions yet'
            if not rest.isdecimal() or not 0 < int(rest) <= len(found): return f'no suggestion {rest}; /check suggest lists them'
            return change(lambda its: add(its, found[int(rest) - 1]))
        if verb == 'clear':
            def clear(its):
                n = len(its)
                its[:] = [it for it in its if it['state'] != 'done']
                return f'cleared {n - len(its)} done item(s)'
            return change(clear)
        if verb in ('done', 'skip', 'undo', 'rm') and rest:
            n, _, reason = rest.partition(' ')
            def edit(its):
                if not n.isdecimal() or (i := find(its, n)) is None: return f'no item {n}'
                if verb == 'rm': its.pop(i)
                else: its[i].update(state=dict(done='done', skip='skipped', undo='open')[verb], reason=reason.strip() if verb == 'skip' else '')
                return render(its) or 'checklist is empty'
            return change(edit)
        return USAGE

    def status(agent):
        items = store.data['items']
        return f'check {sum(it["state"] != "open" for it in items)}/{len(items)}' if items else None

    def before_turn(agent, prompt):
        rows = [f'{i}. {it["text"]}' + (' (blocks git_commit and git_remote push until done)' if it['gate'] else '')
                for i, it in enumerate(store.data['items'], 1) if it['state'] == 'open']
        if not rows: return None
        return {'context': 'Open items on the checklist the person pinned:\n' + '\n'.join(rows) +
                '\nCall the `checklist` tool when you complete, skip or add an item. Gating items (marked blocks) are the person\'s to settle: ask them to run `/check done N`.'}

    def before_tool(agent, name, args):
        if name not in GATED or (name == 'git_remote' and args.get('op') != 'push'): return None
        items = store.reload()['items']
        if store.problem: return f'checklist: the saved list cannot be read: {store.problem}'
        gate = next((it for it in items if it['gate'] and it['state'] == 'open'), None)
        return None if gate is None else f'checklist: {gate["text"]}'

    def checklist(
        action:str, # `check` when an item is done, `skip` when it will not be done, `add` for a new item
        item:str, # the open item's number or text; for `add`, the new item's text
        reason:str='', # why, for `skip`
    )->str:
        "Update the checklist the person pinned when you complete, skip or add an item. A gating item cannot be checked or skipped here: ask the person to run `/check done N`."
        def run(items):
            if action == 'add': return add(items, item.strip()) if item.strip() else 'nothing to add: item is empty'
            if action not in ('check', 'skip'): return f'unknown action {action!r}; use check, skip or add'
            if (i := find(items, item, ('open',))) is None:
                return f'no open item matches {item!r}; open items:\n' + '\n'.join(f'{n}. {it["text"]}' for n, it in enumerate(items, 1) if it['state'] == 'open')
            if items[i]['gate']:
                return f'refused: item {i + 1} gates a commit or push and belongs to the person. Ask them to run `/check done {i + 1}` (or `/check skip {i + 1}`); do not retry it here.'
            items[i].update(state='done' if action == 'check' else 'skipped', reason=reason.strip() if action == 'skip' else '')
            return f'{"checked" if action == "check" else "skipped"} {i + 1}: {items[i]["text"]}'
        return change(run)

    reg.tool(checklist)
    reg.command('check', command, 'Show or change the pinned checklist.')
    reg.status(status)
    reg.on('before_turn', before_turn)
    reg.on('before_tool', before_tool)
