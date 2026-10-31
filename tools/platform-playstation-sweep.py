#!/usr/bin/env python3
"""Extract every PLATFORM(PLAYSTATION) conditional block in the Sony drop.

For each `#if/#elif` whose condition mentions PLATFORM(PLAYSTATION), record the
whole conditional it belongs to: every branch's condition, the branch lengths,
and the first lines of each branch, plus whether a branch exists for the
non-PlayStation case.  The point is classification by reading: a block that
*adds* a platform path is inert for a GTK-only oracle, a block that *replaces*
shared logic is a deviation candidate.

The conditional stack is built in one forward pass (a backwards walk mis-attributes
a line inside a nested `#if` to that inner block), so every PS line maps to the
innermost conditional that really contains it.

Usage: platform-playstation-sweep.py --root <WebKit root> [--json out.json]
                                       [--subdirs Source/WTF,Source/bmalloc,...]

`--subdirs` defaults to the two directories docs/106 covered; the wider tree
(`Source/WTF`, `Source/bmalloc`, `Source/WebKit`) uses the same extractor, and
bmalloc spells the macro `BPLATFORM(PLAYSTATION)` — the regex matches both.
"""
import argparse, json, os, re

PS = re.compile(r'B?PLATFORM\s*\(\s*PLAYSTATION\s*\)')
DIRECTIVE = re.compile(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b')


def scan(path, rel):
    with open(path, 'r', errors='replace') as f:
        lines = f.read().split('\n')
    blocks = []          # list of dicts, in file order
    stack = []           # indices into blocks (open conditionals)
    for i, l in enumerate(lines):
        m = DIRECTIVE.match(l)
        if m:
            d = m.group(1)
            if d in ('if', 'ifdef', 'ifndef'):
                blocks.append({'open': i, 'close': None,
                               'branches': [{'dir': i, 'cond': l.strip(),
                                             'start': i + 1, 'end': None}]})
                stack.append(len(blocks) - 1)
            elif d in ('elif', 'else') and stack:
                b = blocks[stack[-1]]
                b['branches'][-1]['end'] = i
                b['branches'].append({'dir': i, 'cond': l.strip(),
                                      'start': i + 1, 'end': None})
            elif d == 'endif' and stack:
                b = blocks[stack.pop()]
                b['branches'][-1]['end'] = i
                b['close'] = i
            continue
    # now attribute: a block is a PS block if any of its branch conditions
    # mentions PLATFORM(PLAYSTATION)
    out = []
    for b in blocks:
        conds = [x['cond'] for x in b['branches']]
        if not any(PS.search(c) for c in conds):
            continue
        body = []
        for x in b['branches']:
            end = x['end'] if x['end'] is not None else len(lines)
            code = [y.strip() for y in lines[x['start']:end] if y.strip()]
            body.append({'cond': x['cond'], 'nlines': end - x['start'], 'code': code[:8]})
        alt = [x for x in b['branches'] if not PS.search(x['cond'])]
        # line numbers of every PS condition inside this block
        ps_lines = [x['dir'] + 1 for x in b['branches'] if PS.search(x['cond'])]
        out.append({'file': rel, 'line': ps_lines[0], 'ps_cond_lines': ps_lines,
                    'block_open': b['open'] + 1,
                    'block_close': (b['close'] + 1) if b['close'] is not None else None,
                    'conds': conds, 'n_branches': len(b['branches']),
                    'has_alt': bool(alt), 'alt_conds': [x['cond'] for x in alt],
                    'branches': body})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--json')
    ap.add_argument('--subdirs', default='Source/JavaScriptCore,Source/WebCore')
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    rows = []
    for sub in [s for s in a.subdirs.split(',') if s]:
        if not os.path.isdir(os.path.join(root, sub)):
            print('missing subdir', sub)
            continue
        for dirpath, _, files in os.walk(os.path.join(root, sub)):
            for fn in sorted(files):
                if not fn.endswith(('.cpp', '.h', '.mm', '.c')):
                    continue
                p = os.path.join(dirpath, fn)
                rows += scan(p, os.path.relpath(p, root))
    rows.sort(key=lambda r: (r['file'], r['line']))
    nlines = 0
    for r in rows:
        nlines += len(r['ps_cond_lines'])
    print(f'{len(rows)} PS conditional blocks, {nlines} PS condition lines, '
          f'{len(set(r["file"] for r in rows))} files')
    print(f'{sum(1 for r in rows if r["has_alt"])} blocks with a non-PS alternative branch')
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(rows, f, indent=1)
        print('wrote', a.json)


if __name__ == '__main__':
    main()
