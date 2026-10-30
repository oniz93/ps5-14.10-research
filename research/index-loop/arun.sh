#!/usr/bin/env bash
# docs/81 arm runner: one page, quarantine OFF (run_nq.sh), beacons + request log scored from the server.
set -u
PORT=${PORT:-9721}
PAGE=${PAGE:-appcache-loop.html}
SECS=${SECS:-40}
TAG=${TAG:-acA}
QS=${QS:-}
cd /home/<user>/wk
pkill -f "[h]ttp.server $PORT" 2>/dev/null
pkill -f "[s]rv.py $PORT" 2>/dev/null
sleep 0.3
( cd /tmp/wkp && nohup python3 /tmp/wkp/srv.py "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
sleep 1
./run_nq.sh "http://127.0.0.1:$PORT/$PAGE$QS" "$SECS" > "/tmp/H_$TAG.log" 2>&1
echo "RC=$?"
grep -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped" "/tmp/H_$TAG.log" || echo "access: none"
grep -a "^EXIT=" "/tmp/H_$TAG.log" | tail -1
grep -a -oE "GET /ev\?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("  B " + urllib.parse.unquote(l.strip()))'
echo "  -- requests --"
grep -a -oE '"GET [^"]*" [0-9]+' "/tmp/srv$PORT.log" | head -12
pkill -f "[s]rv.py $PORT" 2>/dev/null
