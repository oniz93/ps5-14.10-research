#!/usr/bin/env bash
# Same as run_asan_page.sh but with the allocator quarantine disabled, so a freed object can actually be reused
# inside the run. Use this when testing whether a reclaimed slot is reachable: with quarantine on, ASAN parks
# freed memory and every reclaim test is a false negative.
#
#   ./run_nq.sh http://127.0.0.1:8904/index.html [seconds]
set -u
BIN=${MINIBROWSER:-$HOME/wk/WebKit/WebKitBuild/ASAN/bin/MiniBrowser}
URL=${1:?usage: run_nq.sh <url> [seconds]}
SECS=${2:-25}

[ -x "$BIN" ] || { echo "no MiniBrowser at $BIN" >&2; exit 2; }

export ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0}
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export GDK_BACKEND=x11

timeout "$SECS" xvfb-run -a "$BIN" "$URL" 2>&1
echo "EXIT=$?"
