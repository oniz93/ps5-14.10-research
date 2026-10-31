#!/usr/bin/env python3
"""Classify the files a port's own CMake source list adds, for the Sony drop.

`docs/106` §7 recorded the blind spot: `PlatformPlayStation.cmake` lists files
that carry no `#if PLATFORM(PLAYSTATION)` at all, so a grep-based audit cannot
see them.  This tool answers the only question that matters for such a file:

  shared   the same relative path is listed by `Sources.txt` / `SourcesGTK.txt`
           / `SourcesWPE.txt` (or is a header), i.e. the port compiles the very
           file every other port compiles -> no deviation is possible.
  ps-only  nothing else lists it.  Then, for every `Class::method(` definition
           in the file, is the same definition also present outside the port's
           own directories?
             replace  yes -> the port supplies a *different* body for a shared
                      declaration: the deviation shape, one row per method.
             add      no  -> the port defines a declaration whose shared
                      definition is compiled out elsewhere (a stub in the
                      docs/106 sense).

Usage: ps-file-list-sweep.py --root <WebKit root> [--port PlayStation]
                             [--dir Source/WebCore] [--json out.json]
"""
import argparse, json, os, re

# CMake list entries look like `    path/to/File.cpp`; only extensions we can
# read are considered (headers are declarations, never a body).
EXTLIST = ('.cpp', '.mm', '.c', '.h')
DEF = re.compile(r'^[A-Za-z_][\w:<>,*&\s]*?\b([A-Za-z_]\w*)::([A-Za-z_]\w*)\s*\(', re.M)


def listed(cmake, root, want_ext=True):
    out = []
    if not os.path.exists(cmake):
        return out
    for line in open(cmake, errors='replace'):
        s = line.strip()
        if s.startswith('#'):
            continue
        for tok in re.findall(r'[A-Za-z0-9_/+.-]*[A-Za-z0-9_+-]\.(?:cpp|mm|h)\b', s):
            if tok.endswith('.cmake') or tok not in out:
                if tok.endswith('.cmake'):
                    continue
                out.append(tok)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--dir', default='Source/WebCore')
    ap.add_argument('--port', default='PlayStation')
    ap.add_argument('--json')
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    d = os.path.join(root, a.dir)
    port_files = listed(os.path.join(d, f'Platform{a.port}.cmake'), root)
    core = set(listed(os.path.join(d, 'Sources.txt'), root))
    shared = set(core)
    for f in ('SourcesGTK.txt', 'SourcesWPE.txt', 'SourcesCocoa.txt', 'SourcesWin.txt'):
        shared |= set(listed(os.path.join(d, f), root))

    # every definition outside the port's own directories, for the `replace` test
    others = {}
    for dirpath, _, files in os.walk(d):
        for fn in files:
            if not fn.endswith(('.cpp', '.mm')):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, d)
            if '/playstation/' in rel or rel.startswith('platform/playstation/'):
                continue
            try:
                txt = open(p, errors='replace').read()
            except OSError:
                continue
            for cls, meth in DEF.findall(txt):
                others.setdefault(f'{cls}::{meth}', set()).add(rel)

    # which of those files does the *shared* build compile?  A port file that
    # displaces a definition from a shared source file is a real replacement;
    # one that merely mirrors another port's file is the normal abstraction.
    shared_src = core
    port_lists = set()
    for n in ('GTK', 'WPE', 'Mac', 'Win'):
        port_lists |= set(listed(os.path.join(d, f'Platform{n}.cmake'), root))

    rows = []
    for f in port_files:
        p = os.path.join(d, f)
        row = {'file': f, 'exists': os.path.exists(p), 'kind': None,
               'replaces': [], 'defines': 0}
        if not row['exists']:
            row['kind'] = 'missing'
            rows.append(row)
            continue
        if f.endswith('.h') or f in shared:
            row['kind'] = 'shared'
            rows.append(row)
            continue
        txt = open(p, errors='replace').read()
        defs = DEF.findall(txt)
        row['defines'] = len(defs)
        row['kind'] = 'ps-only'
        for cls, meth in defs:
            key = f'{cls}::{meth}'
            hit = sorted(x for x in others.get(key, ()) if x != f)
            if not hit:
                continue
            shared_hit = [x for x in hit if x in shared_src]
            row['replaces'].append({'def': key, 'also': hit[:3],
                                    'from_shared': shared_hit[:2],
                                    'displaces': bool(shared_hit)})
        rows.append(row)

    import collections
    print(a.dir, a.port, dict(collections.Counter(r['kind'] for r in rows)))
    for r in rows:
        if r['kind'] == 'missing':
            print('  MISSING from the drop:', r['file'])
    for r in rows:
        if r['kind'] == 'ps-only' and r['replaces']:
            dis = [x for x in r['replaces'] if x['displaces']]
            tag = f"DISPLACES SHARED {len(dis)}" if dis else 'port-abstracted'
            print(f"{r['file']}  {tag}  ({len(r['replaces'])} same-name defs)")
            for x in dis[:6]:
                print(f"    {x['def']} <- shared {x['from_shared']}")
    if a.json:
        with open(a.json, 'w') as fh:
            json.dump(rows, fh, indent=1)
        print('wrote', a.json)


if __name__ == '__main__':
    main()
