#!/usr/bin/env bash
# docs/92 one-arm runner for caps13.html: fresh port, quarantine OFF, beacons in arrival order + crash frame.
# usage: c13run.sh <tag> <port> <secs> <query>
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/caps13.html?$Q' $SECS" > "/tmp/S_c13_$TAG.log" 2>&1 < /dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    s=l.strip().split("/ev?m=",1)[1]
    print("  " + urllib.parse.unquote(s))'
echo "--- abort:"
grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED" "/tmp/S_c13_$TAG.log" || echo "  access: none"
grep -a -m1 -A16 -E "ERROR: AddressSanitizer" "/tmp/S_c13_$TAG.log" | sed 's/^/  | /' || true
echo "--- sites:"
grep -a -oE "ImageBitmap[A-Za-z]*\.cpp:[0-9]+|ByteArrayPixelBuffer\.cpp:[0-9]+|SerializedScriptValue\.cpp:[0-9]+|MessagePort\.cpp:[0-9]+|WorkerMessagingProxy\.cpp:[0-9]+|LocalDOMWindow\.cpp:[0-9]+|Optional\.h:[0-9]+" "/tmp/S_c13_$TAG.log" | sort | uniq -c | sed 's/^/  /'
grep -a "^EXIT=" "/tmp/S_c13_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
