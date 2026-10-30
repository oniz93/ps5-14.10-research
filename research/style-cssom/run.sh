#!/bin/bash
# Run one case of research/style-cssom/index.html against the local ASAN oracle (build box), quarantine
# OFF, and print the sanitizer verdict plus the page's beacons.  The page needs three files served
# (index.html, s.css, m.css, ifr.html), so this copies the whole directory to /tmp/wks on the box,
# kills any stale python http.server first, and serves on the given port.
#
#   ./run.sh <port> <case> [seconds] [extra-query]
set -u
PORT=${1:?usage: run.sh <port> <case> [seconds] [extra-query]}
CASE=${2:?}
SECS=${3:-18}
EXTRA=${4:-}
BOX=teo@<lab-ip>
SRC=$(cd "$(dirname "$0")" && pwd)

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" 'pkill -f "[h]ttp.server" ; sleep 0.3; rm -rf /tmp/wks; mkdir -p /tmp/wks' 2>/dev/null
scp -q -r "$SRC"/index.html "$SRC"/s.css "$SRC"/m.css "$SRC"/ifr.html "$BOX:/tmp/wks/"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wks && ( setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 </dev/null & ) ; sleep 1; curl -s -o /dev/null -w 'srv=%{http_code}\n' http://127.0.0.1:$PORT/index.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd ~/wk && timeout 60 distrobox enter -n wk --no-tty -- bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/index.html?case=$CASE$EXTRA' $SECS" > "/tmp/cssom_$CASE.log" 2>&1
echo "===== case=$CASE port=$PORT extra=$EXTRA"
grep -m1 "ERROR: AddressSanitizer" "/tmp/cssom_$CASE.log" | sed 's/^.*ERROR/ERROR/'
grep -m1 -E "WRITE of size|READ of size" "/tmp/cssom_$CASE.log" || echo "access: none"
grep -m1 "SUMMARY:" "/tmp/cssom_$CASE.log" || echo "SUMMARY: none"
grep -m1 -E "SEGV|ABRT|AddressSanitizer:DEADLYSIGNAL" "/tmp/cssom_$CASE.log" | sed 's/0x[0-9a-f]*/0xADDR/' || true
grep -m1 -E "#0 |#1 |#2 |#3 |#4 " "/tmp/cssom_$CASE.log" | sed 's/0x[0-9a-f]*/0xADDR/' || true
grep -m1 "EXIT=" "/tmp/cssom_$CASE.log"
echo "-- beacons:"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "grep -a -o 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("   " + urllib.parse.unquote(l.strip()))'
