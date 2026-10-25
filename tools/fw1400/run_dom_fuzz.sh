#!/usr/bin/env bash
# Drive dom_fuzz.js through the ASAN MiniBrowser build, one process per seed.
#
# Why one process per seed: an ASAN abort kills the browser, so the seed in the log is the whole
# reproducer. Running many seeds in one process would lose the association between a report and
# the input that caused it, which is the only thing that makes a crash useful.
#
# Usage (inside the distrobox container, after the build finishes):
#   ./run_dom_fuzz.sh [first_seed] [last_seed] [seconds_per_seed]
#
# Exit codes from MiniBrowser:
#   0   the browser exited on its own (page finished, or window closed)
#   124 still running when the timeout fired - treated as clean
#   else  candidate crash; the log is kept and checked for an AddressSanitizer report

set -u

FIRST=${1:-1}
LAST=${2:-200}
# A full 220-iteration run takes about one second; the wall clock is dominated by MiniBrowser
# startup. 15s leaves ample margin without wasting 90x per seed.
PER=${3:-10}

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${MINIBROWSER:-$HOME/wk/WebKit/WebKitBuild/ASAN/bin/MiniBrowser}"
OUT="$HERE/fuzz-out"
mkdir -p "$OUT"
# Results are per-sweep. Leftover files from an earlier run made a clean 300-seed sweep summarise as
# "nonzero=46" because those seeds came from a run where the browser could not start at all.
rm -f "$OUT/nonzero.txt" "$OUT/crashes.txt" "$OUT/incomplete.txt"

if [ ! -x "$BIN" ]; then
    echo "no MiniBrowser at $BIN" >&2
    echo "set MINIBROWSER=/path/to/MiniBrowser or finish the build first" >&2
    exit 2
fi

# GTK needs a display; Xvfb gives each run a throwaway one and -a picks a free number.
command -v Xvfb >/dev/null || { echo "Xvfb missing: sudo dnf install -y xorg-x11-server-Xvfb" >&2; exit 2; }

# Preflight: a clean sweep is worthless if the binary was not actually instrumented.
# Check the dynamic dependency rather than the build flags - ldd is harder to fool.
if ! ldd "$BIN" 2>/dev/null | grep -q libasan; then
    echo "PREFLIGHT FAILED: $BIN does not link libasan, so a clean run would prove nothing." >&2
    ldd "$BIN" 2>/dev/null | grep -iE "asan|ubsan" >&2 || echo "  (no sanitizer runtime linked)" >&2
    exit 3
fi
echo "preflight: ASAN runtime linked"

# And confirm the sanitizer reports rather than merely links: a deliberate UAF must be caught.
PROBE=$(mktemp -d)
# The read must be volatile and feed a printf: a plain store after free is dead code and GCC at
# -O1 removes it, which made a working sanitizer look silent during bring-up.
cat > "$PROBE/t.c" <<'EOF'
#include <stdlib.h>
#include <stdio.h>
int main(void) { volatile char *p = malloc(8); if (!p) return 2; p[0] = 7; free((void*)p);
    printf("%d\n", p[0]); return 0; }
EOF
if cc -fsanitize=address -O1 -o "$PROBE/t" "$PROBE/t.c" 2>/dev/null; then
    if ! "$PROBE/t" 2>&1 | grep -q "AddressSanitizer"; then
        echo "PREFLIGHT FAILED: a deliberate heap-use-after-free produced no report" >&2
        exit 3
    fi
    echo "preflight: deliberate use-after-free detected (oracle works)"
else
    echo "preflight: could not build the ASAN probe - continuing anyway" >&2
fi
rm -rf "$PROBE"

# Beacon server: proves the page actually executed. MiniBrowser does not forward console output,
# and an exit code cannot tell a completed run from a page that never loaded.
BEACON_PORT=${BEACON_PORT:-8123}
mkdir -p "$OUT/beacon"

# Reclaim the port first. A leftover server from a previous sweep keeps the socket and silently
# swallows every beacon while its own log file has been deleted, so the sweep reports clean with
# zero evidence - which happened once already.
old_pid=$(ss -ltnp 2>/dev/null | awk -v port=":$BEACON_PORT" '$4 ~ port {print $NF}' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)
if [ -n "${old_pid:-}" ]; then
    kill "$old_pid" 2>/dev/null && echo "preflight: reclaimed port $BEACON_PORT from pid $old_pid"
    sleep 1
fi

# -u matters: http.server prints its banner to stdout, which is block-buffered when redirected, so
# the readiness check below could never see it and the server looked dead while running fine.
( cd "$OUT/beacon" && exec python3 -u -m http.server "$BEACON_PORT" --bind 127.0.0.1 > "$OUT/http.log" 2>&1 ) &
echo $! > "$OUT/http.pid"
trap '[ -f "$OUT/http.pid" ] && kill "$(cat "$OUT/http.pid")" 2>/dev/null' EXIT

# Do not sweep against a server that never came up.
for _ in 1 2 3 4 5 6; do
    grep -q "Serving HTTP" "$OUT/http.log" 2>/dev/null && break
    sleep 0.5
done
if ! grep -q "Serving HTTP" "$OUT/http.log" 2>/dev/null; then
    echo "PREFLIGHT FAILED: beacon server did not start on port $BEACON_PORT" >&2
    sed -n '1,6p' "$OUT/http.log" >&2
    exit 4
fi
echo "preflight: beacon server up on $BEACON_PORT"
BEACON="http://127.0.0.1:$BEACON_PORT"

# detect_stack_use_after_return=0 is mandatory, not tuning: JSC finds roots by scanning the raw
# stack (ConservativeRoots::genericAddSpan), and ASAN's fake stack puts frames in a separate region,
# so the scanner walks addresses that are not mapped and SEGVs. Every run aborted in the GC that way
# and looked like a WebKit crash. WebKit's own run-webkit-tests sets this too.
export ASAN_OPTIONS="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1"
export WEBKIT_DISABLE_COMPOSITING_MODE=1        # keep rendering in-process, so faults land here
export GDK_BACKEND=x11

crashes=0
clean=0
completed=0

for seed in $(seq "$FIRST" "$LAST"); do
    log="$OUT/seed-$seed.log"
    # A wrapper page rather than a ?seed= query: file:// URLs may drop the query, which would run
    # seed 1 for every iteration and still report clean.
    wrapper="$OUT/beacon/run-$seed.html"
    cp "$HERE/dom_fuzz.js" "$OUT/beacon/dom_fuzz.js"
    printf '<!doctype html><meta charset="utf-8"><script>window.__SEED=%d;window.__BEACON="%s";</script><script src="dom_fuzz.js"></script>\n' "$seed" "$BEACON" > "$wrapper"
    # Wait for DONE rather than for the timeout. The fuzzer needs about a second of real work; the
    # rest of the per-seed cost is MiniBrowser startup, so blocking for the full timeout meant ~12
    # of every 13 seconds were idle. setsid makes $spid a process-group leader, so one signal takes
    # down xvfb-run, Xvfb and MiniBrowser together instead of orphaning them.
    setsid timeout "$PER" xvfb-run -a "$BIN" "http://127.0.0.1:$BEACON_PORT/run-$seed.html" >"$log" 2>&1 &
    spid=$!
    finished=0
    for _ in $(seq 1 $((PER * 10))); do
        if grep -q "DONE-seed$seed" "$OUT/http.log" 2>/dev/null; then finished=1; break; fi
        kill -0 "$spid" 2>/dev/null || break
        sleep 0.1
    done
    kill -TERM -"$spid" 2>/dev/null
    wait "$spid" 2>/dev/null
    rc=$?
    rm -f "$wrapper"

    if grep -q "AddressSanitizer" "$log"; then
        crashes=$((crashes + 1))
        kind=$(grep -o "ERROR: AddressSanitizer: [a-z-]*" "$log" | head -1)
        echo "CRASH seed=$seed rc=$rc $kind"
        echo "$seed" >> "$OUT/crashes.txt"
        continue
    fi

    # 143/137 = our own group kill when a seed never reached DONE; that is the timeout path.
    if [ "$finished" -eq 1 ] || [ "$rc" -eq 124 ] || [ "$rc" -eq 0 ] || [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then
        if [ "$finished" -eq 1 ]; then
            completed=$((completed + 1))
        else
            echo "NOT-COMPLETED seed=$seed rc=$rc (page never reached DONE - result discarded)"
            echo "$seed" >> "$OUT/incomplete.txt"
        fi
        clean=$((clean + 1))
        rm -f "$log"
        [ $((clean % 20)) -eq 0 ] && echo "  clean=$clean last_seed=$seed"
        continue
    fi

    # a non-ASAN crash still matters: keep it, it is a signal the sanitizer may have missed
    echo "NONZERO seed=$seed rc=$rc (kept: $log)"
    echo "$seed" >> "$OUT/nonzero.txt"
done

echo
[ -f "$OUT/http.pid" ] && kill "$(cat "$OUT/http.pid")" 2>/dev/null
rmdir "$OUT/beacon" 2>/dev/null
echo "done: clean=$clean completed=$completed asan_crashes=$crashes nonzero=$([ -f "$OUT/nonzero.txt" ] && wc -l < "$OUT/nonzero.txt" || echo 0) incomplete=$([ -f "$OUT/incomplete.txt" ] && wc -l < "$OUT/incomplete.txt" || echo 0)"
[ -f "$OUT/crashes.txt" ] && echo "seeds: $(tr '\n' ' ' < "$OUT/crashes.txt")"
