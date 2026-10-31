#!/usr/bin/env bash
# docs/97 one-arm runner for caps16.html: fresh port, quarantine OFF, beacons in arrival order,
# the sanitizer frame and the EXIT line.
# usage: c16run.sh <tag> <port> <secs> <query>
#   e.g. c16run.sh w 9140 25 'arm=w'
#        c16run.sh grv 9141 25 'arm=w&only=K,GR,RB,RBs'
#        c16run.sh fl 9142 20 'arm=fl'
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/caps16.html?$Q' $SECS" > "/tmp/S_c16_$TAG.log" 2>&1 < /dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    s=l.strip().split("/ev?m=",1)[1]
    print("  " + urllib.parse.unquote(s))' || true
echo "--- abort:"
grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED|CRASH" "/tmp/S_c16_$TAG.log" || echo "  access: none"
grep -a -m1 -A16 -E "ERROR: AddressSanitizer|SEGV" "/tmp/S_c16_$TAG.log" | sed 's/^/  | /' || true
echo "--- sites:"
grep -a -oE "Crypto\.cpp:[0-9]+|TextEncoder\.cpp:[0-9]+|ArrayBufferView\.h:[0-9]+|JSArrayBufferView[A-Za-z]*\.h:[0-9]+|JSTypedArray[A-Za-z]*\.h:[0-9]+|memcpy|memset|U8_APPEND" "/tmp/S_c16_$TAG.log" | sort | uniq -c | sed 's/^/  /'
echo "--- addresses named:"
grep -a -oE "SEGV on unknown address 0x[0-9a-f]+|WRITE of size [0-9]+|READ of size [0-9]+" "/tmp/S_c16_$TAG.log" | head -4 | sed 's/^/  /'
grep -a "^EXIT=" "/tmp/S_c16_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
