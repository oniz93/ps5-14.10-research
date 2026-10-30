#!/bin/bash
# Run one page against the local ASAN oracle on the build box, quarantine OFF, and print the
# sanitizer verdict plus the page's beacons.  Same contract as ../cve-2026-43715/run-page.sh, kept
# separate so docs/70 can quote one command without a PAGE= override.
#
#   ./run-page.sh <port> "<query-string>" <tag>
set -u
PORT=${1:?usage: run-page.sh <port> \"<query>\" <tag>}
Q=${2:?}
TAG=${3:?}
PAGE=${PAGE:-sink-window.html}
BOX=teo@<lab-ip>
scp -q "$(dirname "$0")/$PAGE" "$BOX:/tmp/wkp/index.html"
# Kill stale servers in their OWN ssh call: `pkill -f` matches the whole remote command line, and the
# start command below contains "http.server" itself, so a combined call kills its own shell.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server' ; true"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && ( setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 </dev/null & ) ; sleep 1; curl -s -o /dev/null -w 'srv=%{http_code}\n' http://127.0.0.1:$PORT/index.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd ~/wk && timeout 90 distrobox enter -n wk --no-tty -- bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/index.html?$Q' 40" > "/tmp/run_$TAG.log" 2>&1
echo "===== $TAG  q=$Q"
grep -m1 "ERROR: AddressSanitizer" "/tmp/run_$TAG.log" | sed 's/^.*ERROR/ERROR/'
grep -m1 -E "WRITE of size|READ of size" "/tmp/run_$TAG.log" || echo "access: none"
grep -m1 "#0 " "/tmp/run_$TAG.log" | sed 's/0x[0-9a-f]*/0xADDR/'
grep -m1 "SUMMARY:" "/tmp/run_$TAG.log" || echo "SUMMARY: none"
grep -m1 "is located" "/tmp/run_$TAG.log"
echo "-- beacons:"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "grep -a -o 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("   " + urllib.parse.unquote(l.strip()))'
