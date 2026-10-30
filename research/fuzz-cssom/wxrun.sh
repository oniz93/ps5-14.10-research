#!/usr/bin/env bash
# docs/89 one-arm runner for a capability page: fresh port, quarantine OFF, then the beacon log.
# usage: wxrun.sh <port> <page> <secs> [query]
set -u
PORT=${1:?}; PAGE=${2:?}; SECS=${3:-25}; Q=${4:-}
for p in $(pgrep -f 'http[.]server' 2>/dev/null); do kill "$p" 2>/dev/null; done
sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
URL="http://127.0.0.1:$PORT/$PAGE"
[ -n "$Q" ] && URL="$URL?$Q"
distrobox enter wk --no-tty -- bash -lc "bash ~/wk/run_nq.sh '$URL' $SECS" > "/tmp/S_$PAGE.$PORT.log" 2>&1
echo "=== $PAGE port=$PORT secs=$SECS q=$Q"
echo "--- beacons:"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print(urllib.parse.unquote(l.strip()))'
echo "--- sanitizer:"
grep -a -m5 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped|zapped" "/tmp/S_$PAGE.$PORT.log" || echo "  access: none"
grep -a -m1 -A12 -E "ERROR: AddressSanitizer" "/tmp/S_$PAGE.$PORT.log" | sed 's/^/  | /' || true
grep -a "^EXIT=" "/tmp/S_$PAGE.$PORT.log" | tail -1
for p in $(pgrep -f 'http[.]server' 2>/dev/null); do kill "$p" 2>/dev/null; done
