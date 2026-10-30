#!/usr/bin/env bash
# docs/80 §6 arm runner: one page, quarantine OFF (run_nq.sh), beacons scored from the server log.
set -u
PORT=${PORT:-9711}
PAGE=${PAGE:-track-clients.html}
SECS=${SECS:-45}
TAG=${TAG:-track1}
cd /home/<user>/wk
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
( cd /tmp/wkp && nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
sleep 1
./run_nq.sh "http://127.0.0.1:$PORT/$PAGE" "$SECS" > "/tmp/H_$TAG.log" 2>&1
echo "RC=$?"
grep -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped" "/tmp/H_$TAG.log" || echo "access: none"
grep -a "^EXIT=" "/tmp/H_$TAG.log" | tail -1
grep -a -oE "GET /ev\?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("  B " + urllib.parse.unquote(l.strip()))'
pkill -f "[h]ttp.server $PORT" 2>/dev/null
