#!/usr/bin/env bash
# docs/105 one-arm ASAN runner for the SVG-font corpus.  Kills only its OWN port and its own
# MiniBrowser (another session may be running a page on the same box), quarantine OFF.
#   usage: g10asan.sh <tag> <port> <secs> "<query>"
set -u
BOX=teo@<lab-ip>
TAG=${1:?}; PORT=${2:?}; SECS=${3:-45}; Q=${4:-}
ROOT=$(cd "$(dirname "$0")" && pwd)
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1
ssh -o BatchMode=yes "$BOX" "mkdir -p /tmp/wkp/sf" >/dev/null 2>&1
scp -q "$ROOT/corpus.html" "$BOX:/tmp/wkp/sf/corpus.html" || exit 2
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp/sf && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &) ; sleep 1 ; curl -s -o /dev/null -w 'srv=%{http_code}\n' 'http://127.0.0.1:$PORT/corpus.html'"
ssh -o BatchMode=yes "$BOX" \
  "distrobox enter wk --no-tty -- bash -lc \"ASAN_OPTIONS='$AO' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/corpus.html?$Q' $SECS\"" \
  > "/tmp/L_$TAG.log" 2>&1
# only this run's browser
ssh -o BatchMode=yes "$BOX" "pkill -f 'MiniBrowser http://127.0.0.1:$PORT/' ; pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1

echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
ssh -o BatchMode=yes "$BOX" "grep -ao 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null \
  | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys, urllib.parse
for l in sys.stdin: print("  " + urllib.parse.unquote(l.strip()))'
echo "--- crash/abort:"
if grep -aqE "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED|Segmentation fault" "/tmp/L_$TAG.log"; then
  grep -a -m6 -E "ERROR: AddressSanitizer|SUMMARY|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED|Segmentation fault" "/tmp/L_$TAG.log" | sed 's/^/  /'
else
  echo "  access: none"
fi
grep -a "^EXIT=" "/tmp/L_$TAG.log" | tail -1
