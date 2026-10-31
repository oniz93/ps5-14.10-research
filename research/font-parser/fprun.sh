#!/usr/bin/env bash
# docs/99 font-parser runner: fresh port, ASAN quarantine off, beacons in arrival
# order so an abort is named by the last BEG without a RES.
# usage: fprun.sh <tag> <port> <secs> [query]
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-120}; Q=${4:-}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/corpus.html?$Q' $SECS" > "/tmp/L_$TAG.log" 2>&1 < /dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    print(urllib.parse.unquote(l.strip().split("/ev?m=",1)[1]))'
echo "--- crash/abort:"
grep -a -m8 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|Segmentation fault" "/tmp/L_$TAG.log" || echo "  access: none"
grep -a "^EXIT=" "/tmp/L_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
