#!/usr/bin/env bash
# docs/90 one-arm runner for caps11.html.  The ASAN oracle is the Linux box teo@<lab-ip>;
# pages are served from /tmp/wkp there on a fresh port, quarantine is OFF (run_nq.sh).
# usage: c11run.sh <tag> <port> <secs> <query> [asan_options]
set -u
BOX=teo@<lab-ip>
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}; AOPT=${5:-}
ROOT=$(cd "$(dirname "$0")" && pwd)
RUN="bash ~/wk/run_nq.sh"
if [ -n "$AOPT" ]; then RUN="env ASAN_OPTIONS=$AOPT bash ~/wk/run_nq.sh"; fi

# 1. kill stale servers in their own call: `pkill -f` matches the whole remote command line.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server' ; true" >/dev/null 2>&1
sleep 0.3

# 2. ship the page and start a fresh server on a fresh port
scp -q "$ROOT/caps11.html" "$BOX:/tmp/wkp/caps11.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &) ; sleep 1 ; curl -s -o /dev/null -w 'srv=%{http_code}\n' 'http://127.0.0.1:$PORT/caps11.html'"

# 3. run one arm
ssh -o BatchMode=yes "$BOX" \
  "distrobox enter wk --no-tty -- bash -lc \"$RUN 'http://127.0.0.1:$PORT/caps11.html?$Q' $SECS\"" \
  > "/tmp/S_c11_$TAG.log" 2>&1

echo "=== $TAG port=$PORT secs=$SECS q=$Q"
echo "--- beacons:"
ssh -o BatchMode=yes "$BOX" "grep -ao 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null \
  | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys, urllib.parse
for l in sys.stdin: print(urllib.parse.unquote(l.strip()))'
echo "--- abort / sanitizer:"
if grep -aqE "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|Segmentation fault" "/tmp/S_c11_$TAG.log"; then
  grep -a -m6 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|Segmentation fault" "/tmp/S_c11_$TAG.log" | sed 's/^/  /'
  echo "  --- top backend frames:"
  grep -a -m3 -oE "SerializedScriptValue\.cpp:[0-9]+|MessagePort\.cpp:[0-9]+|LocalDOMWindow\.cpp:[0-9]+|BroadcastChannel\.cpp:[0-9]+|WorkerMessagingProxy\.cpp:[0-9]+|ServiceWorkerContainer\.cpp:[0-9]+|JSDataView\.cpp:[0-9]+|ImageBitmap\.cpp:[0-9]+|ImageBitmapBacking\.cpp:[0-9]+|JSDOMGlobalObject\.cpp:[0-9]+" "/tmp/S_c11_$TAG.log" | sort | uniq -c | sed 's/^/  /'
else
  echo "  access: none"
fi
grep -a "^EXIT=" "/tmp/S_c11_$TAG.log" | tail -1
ssh -o BatchMode=yes "$BOX" "pkill -f '[h]ttp.server' ; true" >/dev/null 2>&1
