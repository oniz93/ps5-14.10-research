#!/usr/bin/env python3
"""docs/95 scorer: two-run ASLR diff over the leak-corpus beacons.

Reads two beacon dumps (run A, run B) and the /proc/<WebProcess>/maps snapshot of each run and
answers one question per entry: is there a value that (a) changes between the two runs and
(b) falls inside a mapped region of the WebProcess? A value that is stable across ASLR is a
constant, not a leak; a value that changes but lies outside every mapping (a UUID, a clock) is
not an address either.

usage: diff.py <OUT_A> <OUT_B> <maps_A> <maps_B>
"""
import re, sys

def parse(path):
    d, order, inb = {}, [], False
    for line in open(path, errors='replace').read().splitlines():
        if line.startswith('--- beacons'):
            inb = True; continue
        if line.startswith('--- '):
            inb = False
        if inb and '=' in line:
            k, _, v = line.partition('=')
            if k and not k.startswith('==='):
                if k not in d:
                    order.append(k)
                d[k] = v
    return d, order

def norm(v, port):
    v = re.sub(r':1[0-9]{4}\b', ':PORT', v)
    v = v.replace('tag=' + port, 'tag=PORT')
    return v

def maps(path):
    regs = []
    cur = None
    for line in open(path, errors='replace').read().splitlines():
        if line.startswith('--- sample'):
            continue
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)$', line)
        if m:
            regs.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4).strip()))
    return regs

def where(val, regs):
    try:
        n = int(val, 16)
    except ValueError:
        return None
    for s, e, perms, name in regs:
        if s <= n < e:
            if 'r' not in perms:      # PROT_NONE reservations cover terabytes; not address evidence
                return None
            return '0x%x-0x%x %s %s' % (s, e, perms, name or '[anon]')
    return None

# A real pointer in this build prints with 12-16 hex digits (0x610000010540, 0x000042004100).
# An 8-digit token cannot be one: the WebProcess maps a ~2 TB PROT_NONE reservation, so any
# 8-digit fragment falls "inside a mapping" and would be a false positive (docs/95 §3).
HEX = re.compile(r'0x[0-9a-fA-F]{9,}|(?<![0-9a-fA-F])[0-9a-fA-F]{10,}(?![0-9a-fA-F])')
FRAG = re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{8}(?![0-9a-fA-F])')

def main():
    a_path, b_path, ma_path, mb_path = sys.argv[1:5]
    A, oa = parse(a_path)
    B, ob = parse(b_path)
    MA, MB = maps(ma_path), maps(mb_path)
    portA = re.search(r'part=\d+', A.get('BOOT', '')) and '' or ''
    keys = [k for k in oa if k in B]
    same = [k for k in keys if norm(A[k], portA) == norm(B[k], portA)]
    diff = [k for k in keys if norm(A[k], portA) != norm(B[k], portA)]
    print('entries: A=%d B=%d shared=%d' % (len(A), len(B), len(keys)))
    print('identical across runs: %d' % len(same))
    print('changed across runs:   %d' % len(diff))
    print()
    print('--- values that changed (classified) ---')
    for k in diff:
        va, vb = norm(A[k], portA), norm(B[k], portA)
        ta = HEX.findall(va); tb = HEX.findall(vb)
        hits = []
        for t in ta + tb:
            w = where(t, MA) or where(t, MB)
            if w:
                hits.append(t + ' in ' + w)
        tag = 'ADDRESS-RANGE' if hits else 'not-in-any-mapping'
        print('%-26s %-12s A=%s | B=%s%s' % (k, tag, va[:90], vb[:90], ('  <<< ' + '; '.join(hits)) if hits else ''))
    print()
    frags = [(k, t) for k in diff for t in FRAG.findall(norm(A[k], portA)) + FRAG.findall(norm(B[k], portA))]
    if frags:
        print('--- 8-digit fragments in changed values (UUID halves; not pointers) ---')
        for k, t in frags[:12]:
            print('%-26s %s' % (k, t))
        print()
    print('--- full-width hex tokens (>=10 digits) in values that are identical (constants) ---')
    n = 0
    for k in same:
        for t in HEX.findall(norm(A[k], portA)):
            n += 1
            print('%-26s %s  %s' % (k, t, where(t, MA) or where(t, MB) or 'outside all mappings'))
    if not n:
        print('(none)')
    print()
    print('--- keys only in one run ---')
    for k in oa:
        if k not in B:
            print('A-only: %s=%s' % (k, A[k][:100]))
    for k in ob:
        if k not in A:
            print('B-only: %s=%s' % (k, B[k][:100]))
    print()
    print('VERDICT: %s' % ('a changed value falls inside a mapping — CANDIDATE, needs ground truth'
                           if any((where(t, MA) or where(t, MB)) for k in diff
                                  for t in HEX.findall(norm(A[k], portA)) + HEX.findall(norm(B[k], portA)))
                           else 'no value both changes between runs and lands in a mapping'))

if __name__ == '__main__':
    main()
