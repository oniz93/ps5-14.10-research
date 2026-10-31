#!/usr/bin/env bash
# docs/95 leak-corpus runner: fresh port, quarantine off, beacons in arrival order, plus a
# /proc/<WebProcess>/maps snapshot so a leaked value can be range-classified in the same run.
# usage: lkrun.sh <tag> <port> <secs> [query] [page]
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-30}; Q=${4:-}; PAGE=${5:-leakcorpus.html}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
# sample the WebProcess maps while the page runs (host PID namespace)
( for i in $(seq 1 25); do
    PID=$(pgrep -n -f "WebKitWebProcess") || true
    if [ -n "${PID:-}" ]; then echo "--- sample $i pid=$PID"; cat "/proc/$PID/maps" 2>/dev/null; fi
    sleep 1
  done ) > "/tmp/maps_$TAG.txt" 2>&1 &
MAPS=$!
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/$PAGE?$Q' $SECS" > "/tmp/L_$TAG.log" 2>&1 < /dev/null
kill $MAPS 2>/dev/null; wait $MAPS 2>/dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    s=l.strip().split("/ev?m=",1)[1]
    print(urllib.parse.unquote(s))'
echo "--- maps samples: $(grep -ac '^--- sample' /tmp/maps_$TAG.txt 2>/dev/null || echo 0)"
echo "--- crash/abort:"
grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT" "/tmp/L_$TAG.log" || echo "  access: none"
grep -a "^EXIT=" "/tmp/L_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
