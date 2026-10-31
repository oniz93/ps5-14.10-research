#!/usr/bin/env bash
# Run the SVG-font corpus on the ASAN oracle with the allocator quarantine OFF.
# A crashed WebProcess leaves MiniBrowser alive holding the log pipe, so kill by name after the timeout.
#   ./sfrun.sh TAG PORT SECS "kinds=reach"
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-30}; Q=${4:-}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
fuser -k "$PORT"/tcp 2>/dev/null; sleep 0.3
cd /tmp/wkp/sf || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/corpus.html?$Q' $SECS" > "/tmp/L_$TAG.log" 2>&1 < /dev/null
pkill -x MiniBrowser 2>/dev/null; pkill -x WebKitWebProcess 2>/dev/null; sleep 0.5
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    print(urllib.parse.unquote(l.strip().split("/ev?m=",1)[1]))'
echo "--- server:"
grep -a -c "GET /corpus.html" "/tmp/srv$PORT.log" | sed 's/^/  corpus requests: /'
grep -ao "GET /x_[^ ]*" "/tmp/srv$PORT.log" | sed 's/^/  /'
echo "--- crash/abort:"
grep -a -m8 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED|Segmentation fault" "/tmp/L_$TAG.log" || echo "  access: none"
grep -a "^EXIT=" "/tmp/L_$TAG.log" | tail -1
fuser -k "$PORT"/tcp 2>/dev/null
