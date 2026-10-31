#!/usr/bin/env bash
# docs/108: recompile two WebCore TUs from the same tree at -O2 WITHOUT ASAN, to get a release-shaped
# frame size for the two recursive walkers.  Uses a real WebCore compile command out of the ASAN build's
# ninja graph, so every include path / define is the build's own; only the optimisation level and the
# sanitizer flags change.  Prints nothing but a short summary.
set -u
SRC=/home/<user>/wk/WebKit/Source/WebCore
OUT=/tmp/repro
mkdir -p "$OUT"
cd /home/<user>/wk/WebKit/WebKitBuild/ASAN || exit 1

ninja -t commands 2>/dev/null | grep -m1 -- "-I/home/<user>/wk/WebKit/Source/WebCore/Modules/indexeddb/shared .* -c .*\.cpp" > "$OUT/cc_raw.txt" || { echo "NO COMMAND"; exit 2; }
echo "raw command length: $(wc -c < "$OUT/cc_raw.txt")"

python3 - "$OUT" "$SRC" <<'PY'
import sys, os, shlex, subprocess
out, src = sys.argv[1], sys.argv[2]
raw = open(os.path.join(out,'cc_raw.txt')).read().strip()
toks = shlex.split(raw)
DROPMD = {'-MD','-MT','-MF','-MMD'}
keep=[]
i=0
tgt_in=None
while i < len(toks):
    t=toks[i]
    if t in DROPMD: i+=2; continue
    if t=='-o': i+=2; continue
    if t=='-c': keep.append(t); i+=1; continue
    if t.startswith('-O'): i+=1; continue
    if t.startswith('-fsanitize'): i+=1; continue
    if t.endswith('.cpp'): tgt_in=t; i+=1; continue
    keep.append(t); i+=1
base_flags = keep + ['-O2','-g0','-DNDEBUG']
print("dropped-input:", os.path.basename(tgt_in or '?'))
for name, rel in [('idb','bindings/js/IDBBindingUtilities.cpp'), ('css','css/parser/CSSParserImpl.cpp')]:
    obj = os.path.join(out, name + '.o')
    cmd = base_flags + ['-c', os.path.join(src, rel), '-o', obj]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(name, "COMPILE FAILED", r.stderr.strip().splitlines()[:2])
        continue
    print(name, "compiled", os.path.getsize(obj), "bytes")
    dis = subprocess.run(['objdump','-d','--no-show-raw-insn',obj], capture_output=True, text=True).stdout
    lines = dis.splitlines()
    for want in (['createIDBKeyFromValue'] if name=='idb' else ['consumeRegularRuleList']):
        idx = [i for i,l in enumerate(lines) if l.startswith('0') and want in l and '<' in l]
        if not idx:
            print(name, "symbol not found"); continue
        i0 = idx[0]
        print(" ", lines[i0].strip()[:110])
        for l in lines[i0+1:i0+12]:
            print("   ", l.strip())
PY
