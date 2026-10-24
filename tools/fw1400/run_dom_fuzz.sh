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
PER=${3:-15}

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${MINIBROWSER:-$HOME/wk/WebKit/WebKitBuild/Release/bin/MiniBrowser}"
OUT="$HERE/fuzz-out"
mkdir -p "$OUT"

if [ ! -x "$BIN" ]; then
    echo "no MiniBrowser at $BIN" >&2
    echo "set MINIBROWSER=/path/to/MiniBrowser or finish the build first" >&2
    exit 2
fi

# GTK needs a display; Xvfb gives each run a throwaway one and -a picks a free number.
command -v Xvfb >/dev/null || { echo "Xvfb missing: sudo dnf install -y xorg-x11-server-Xvfb" >&2; exit 2; }

export ASAN_OPTIONS="detect_leaks=0:abort_on_error=1:symbolize=1:handle_abort=1"
export WEBKIT_DISABLE_COMPOSITING_MODE=1        # keep rendering in-process, so faults land here
export GDK_BACKEND=x11

crashes=0
clean=0

for seed in $(seq "$FIRST" "$LAST"); do
    log="$OUT/seed-$seed.log"
    timeout "$PER" xvfb-run -a "$BIN" "file://$HERE/dom_fuzz.js?seed=$seed" >"$log" 2>&1
    rc=$?

    if grep -q "AddressSanitizer" "$log"; then
        crashes=$((crashes + 1))
        kind=$(grep -o "ERROR: AddressSanitizer: [a-z-]*" "$log" | head -1)
        echo "CRASH seed=$seed rc=$rc $kind"
        echo "$seed" >> "$OUT/crashes.txt"
        continue
    fi

    if [ "$rc" -eq 124 ] || [ "$rc" -eq 0 ]; then
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
echo "done: clean=$clean asan_crashes=$crashes nonzero=$(wc -l < "$OUT/nonzero.txt" 2>/dev/null || echo 0)"
[ -f "$OUT/crashes.txt" ] && echo "seeds: $(tr '\n' ' ' < "$OUT/crashes.txt")"
