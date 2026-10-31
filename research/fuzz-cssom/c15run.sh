#!/usr/bin/env bash
# docs/96 one-arm runner for caps15.html: fresh port, quarantine OFF, beacons in arrival order,
# the sanitizer frame and the EXIT line.
# usage: c15run.sh <tag> <port> <secs> <query>
#   e.g. c15run.sh read 9101 25 'arm=read'
#        c15run.sh r1only 9102 25 'arm=read&only=R1'
#        c15run.sh c1 9103 25 'arm=c1'
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/caps15.html?$Q' $SECS" > "/tmp/S_c15_$TAG.log" 2>&1 < /dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    s=l.strip().split("/ev?m=",1)[1]
    print("  " + urllib.parse.unquote(s))' || true
echo "--- abort:"
grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED|CRASH" "/tmp/S_c15_$TAG.log" || echo "  access: none"
grep -a -m1 -A16 -E "ERROR: AddressSanitizer|SEGV" "/tmp/S_c15_$TAG.log" | sed 's/^/  | /' || true
echo "--- sites:"
grep -a -oE "ThreadSafeDataBuffer[A-Za-z]*\.h:[0-9]+|ThreadSafeDataBuffer[A-Za-z]*\.cpp:[0-9]+|IDBKey\.cpp:[0-9]+|IDBBindingUtilities\.cpp:[0-9]+|ArrayBufferView\.h:[0-9]+|ArrayBuffer\.cpp:[0-9]+|Vector\.h:[0-9]+|memcpy" "/tmp/S_c15_$TAG.log" | sort | uniq -c | sed 's/^/  /'
echo "--- addresses named:"
grep -a -oE "SEGV on unknown address 0x[0-9a-f]+|SEGV on unknown address \(|READ of size [0-9]+" "/tmp/S_c15_$TAG.log" | head -4 | sed 's/^/  /'
grep -a "^EXIT=" "/tmp/S_c15_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
