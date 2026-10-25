#!/usr/bin/env bash
# Detached sweep launcher. Survives SSH disconnect: logind no longer kills user processes and the
# sleep targets are masked.
#
# The sweep MUST run inside the distrobox container. Launched on the host, MiniBrowser fails with
# "libasan.so.8: cannot open shared object file" and every seed returns 127 - which the runner
# correctly records as NONZERO rather than a clean pass, but it wastes the whole run.
#
#   Usage: bash ~/wk/sweep.sh [first] [last] [seconds_per_seed]
set -u
FIRST=${1:-1}
LAST=${2:-300}
PER=${3:-15}
LOG=${LOG:-$HOME/wk/fuzz-sweep-$FIRST-$LAST.log}

{
    echo "=== sweep $FIRST..$LAST per=${PER}s started $(date -Is) ==="
    distrobox enter -n wk --no-tty -- bash -lc "cd ~/wk && ./run_dom_fuzz.sh $FIRST $LAST $PER"
    echo "=== sweep finished $(date -Is) exit=$? ==="
} > "$LOG" 2>&1
