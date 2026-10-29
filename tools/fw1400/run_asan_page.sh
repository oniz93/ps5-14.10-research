#!/usr/bin/env bash
# Run a page in the ASAN MiniBrowser under Xvfb and print everything it emits.
#
#   ./run_asan_page.sh http://127.0.0.1:8904/index.html [seconds]
#
# The build is interpreter-only and compiled from Sony's drop, so results here are directly comparable to the
# console for anything that does not depend on the console's missing APIs.
set -u
BIN=${MINIBROWSER:-$HOME/wk/WebKit/WebKitBuild/ASAN/bin/MiniBrowser}
URL=${1:?usage: run_asan_page.sh <url> [seconds]}
SECS=${2:-25}

[ -x "$BIN" ] || { echo "no MiniBrowser at $BIN" >&2; exit 2; }

# detect_stack_use_after_return off: the JSC interpreter trips it constantly and it buries real reports.
# abort_on_error + handle_abort: a sanitizer abort must produce a report, not a silent exit.
export ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1}
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export GDK_BACKEND=x11

timeout "$SECS" xvfb-run -a "$BIN" "$URL" 2>&1
echo "EXIT=$?"
