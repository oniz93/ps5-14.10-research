#!/usr/bin/env bash
# Detached sweep launcher. Runs in the board's user session and survives an SSH disconnect,
# because logind no longer kills user processes and the sleep targets are masked.
#
#   sudo is not needed; ninja and the browser live inside the distrobox container.
#   Usage: bash ~/wk/sweep.sh [first] [last] [seconds_per_seed]
set -u
FIRST=${1:-1}
LAST=${2:-300}
PER=${3:-15}
LOG=${LOG:-$HOME/wk/fuzz-sweep-$FIRST-$LAST.log}

cd "$HOME/wk" || exit 2
{
    echo "=== sweep $FIRST..$LAST per=${PER}s started $(date -Is) ==="
    ./run_dom_fuzz.sh "$FIRST" "$LAST" "$PER"
    echo "=== sweep finished $(date -Is) exit=$? ==="
} > "$LOG" 2>&1
