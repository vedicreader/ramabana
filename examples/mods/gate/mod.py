r"""Hold selected tool calls and release turns for a person's decision."""

import os
import re
import shlex
from pathlib import Path

PATTERNS = (
    r'\brm\s+(?:--?[a-zA-Z-]+\s+)*-(?:[a-zA-Z]*[rR][a-zA-Z]*|-[a-zA-Z-]*recursive)\b',
    r'\bgit\s+push\b[^\n;&|]*(?:--force(?:\b|=)|(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*\b)',
    r'\bgit\s+reset\b[^\n;&|]*--hard\b',
    r'\bgit\s+clean\b(?=[^\n;&|]*\s-[a-zA-Z]*f)(?=[^\n;&|]*\s-[a-zA-Z]*d)[^\n;&|]*',
    r'\bchmod\s+-[a-zA-Z]*R[a-zA-Z]*\b',
    r'\bdd\s+', r'\bmkfs\b', r'>\s*/dev/', r'\bsudo\s+',
)
RELEASE = re.compile(r'\b(?:release|publish|deploy)\b', re.I)


def rm_paths(command):
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=';&|<>')
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return []
    paths = []
    for i, word in enumerate(words):
        if word != 'rm': continue
        operands = False
        for part in words[i + 1:]:
            if part and all(c in ';&|<>' for c in part): break
            if part == '--' and not operands:
                operands = True
                continue
            if operands or not part.startswith('-'): paths.append(part)
    return paths


def file_count(agent, name, cwd):
    host = getattr(agent, 'host', None)
    roots = [Path(r).resolve() for r in getattr(host, 'roots', ())]
    if not roots or any(c in name for c in '*?[$`~'): return None
    base = Path(cwd) if cwd else roots[0]
    if not base.is_absolute():
        base = Path(host.check(cwd)) if callable(getattr(host, 'check', None)) else roots[0] / base
    path = Path(name)
    path = base / path if not path.is_absolute() else path
    if path.is_symlink(): return None
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in roots): return None
    try:
        if callable(getattr(host, 'check', None)): path = Path(host.check(str(path), must_exist=True))
        if path.is_file(): return 1
        if not path.is_dir(): return None
        def fail(error): raise error
        return sum(len(files) for _, _, files in os.walk(path, onerror=fail, followlinks=False))
    except Exception:
        return None


def branch(agent, path=''):
    try:
        from shalya.tools import git_repo
        return git_repo(agent.host, path).info().get('branch') or 'detached or unknown'
    except Exception:
        return 'unknown'


def shell_preview(agent, args):
    command = args.get('command', '')
    rows = [f'$ {command}']
    if re.search(r'\brm\s+', command):
        paths = rm_paths(command)
        if not paths: rows.append('Removal paths could not be determined.')
        for path in paths:
            count = file_count(agent, path, args.get('cwd', ''))
            rows.append(f'{path}: {count} files' if count is not None else f'{path}: file count unavailable')
    if re.search(r'\bgit\s+', command): rows.append(f'branch: {branch(agent, args.get("cwd", ""))}')
    return '\n'.join(rows)


def decision(agent, title, preview):
    ask_user = getattr(agent, 'ask_user', None)
    if not callable(ask_user): return 'gate: ask_user is unavailable; cannot obtain a decision'
    try:
        ask = ask_user(title, preview)
        if ask.answer is True: return None
        return 'gate: ' + (ask.reply() or 'not approved')
    except Exception:
        return 'gate: could not obtain a decision'


def setup(reg):
    enabled = True
    patterns = [re.compile(p) for p in PATTERNS]

    def before_tool(agent, name, args):
        if not enabled: return None
        try:
            if name == 'run_shell':
                if not any(p.search(args.get('command', '')) for p in patterns): return None
                preview = shell_preview(agent, args)
            elif name == 'git_commit' or (name == 'git_remote' and args.get('op') == 'push'):
                action = 'commit' if name == 'git_commit' else 'push'
                preview = f'git {action} {args}\nbranch: {branch(agent, args.get("path", ""))}'
            else: return None
            return decision(agent, 'Confirm risky action', preview)
        except Exception:
            return 'gate: could not evaluate action'

    def before_turn(agent, prompt):
        if not enabled: return None
        try:
            if not RELEASE.search(prompt): return None
            result = decision(agent, 'Confirm release checklist', 'CHANGELOG updated? Version bumped? Tests green?')
            return 'gate: release checklist not confirmed' if result is not None else None
        except Exception:
            return 'gate: could not evaluate turn'

    def command(agent, arg):
        nonlocal enabled
        arg = arg.strip()
        if arg in ('on', 'off'):
            enabled = arg == 'on'
            reg.redraw()
        elif arg.startswith('add '):
            try: patterns.append(re.compile(arg[4:]))
            except re.error as e: return f'gate: invalid regex: {e}'
        elif arg:
            return 'Usage: /gate [on|off|add REGEX]'
        return f'gate {"on" if enabled else "off"}; shell patterns: ' + ', '.join(p.pattern for p in patterns)

    def status(agent): return 'gate' if enabled else None

    reg.on('before_tool', before_tool)
    reg.on('before_turn', before_turn)
    reg.command('gate', command, 'Show or change the decision gate.')
    reg.status(status)
