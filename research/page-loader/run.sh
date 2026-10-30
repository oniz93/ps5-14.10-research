#!/bin/bash
# Run one case of research/page-loader/index.html against the local ASAN oracle (build box) and print
# the sanitizer verdict plus the page's beacons.
#
# The probe drives the highest-risk tail in loader/: a cross-origin <iframe> does a same-document
# fragment navigation, so FrameLoader::loadInSameDocument() dispatches a *synthetic* load event on the
# owner element (FrameLoader.cpp:1229) and then calls m_client->didFinishLoad().  The parent's load
# listener removes the iframe inside that dispatch.  If the frame (and its FrameLoader) could be freed
# by that removal, the tail reads freed memory.
#
# Quarantine is ON here (run_asan_page.sh): the question is "does a bug exist", not "is a slot reused".
#
#   ./run.sh <port> <case> [seconds] [extra-query]
#     case: rm   remove the iframe inside the 2nd load event   (the candidate)
#           div  remove a sibling <div> instead                (control, same timing)
#           none do nothing                                    (control, natural n)
set -u
PORT=${1:?usage: run.sh <port> <case> [seconds] [extra-query]}
CASE=${2:?}
SECS=${3:-20}
EXTRA=${4:-}
BOX=teo@<lab-ip>
SRC=$(cd "$(dirname "$0")" && pwd)

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" 'pkill -f "[h]ttp.server" ; sleep 0.3; rm -rf /tmp/wkp; mkdir -p /tmp/wkp' 2>/dev/null
scp -q "$SRC"/index.html "$SRC"/q.html "$BOX:/tmp/wkp/"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && ( setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 </dev/null & ) ; sleep 1; curl -s -o /dev/null -w 'srv=%{http_code}\n' http://127.0.0.1:$PORT/index.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd ~/wk && timeout 90 distrobox enter -n wk --no-tty -- bash ~/wk/run_asan_page.sh 'http://127.0.0.1:$PORT/index.html?k=$CASE$EXTRA' $SECS" > "/tmp/pl_$CASE.log" 2>&1
echo "===== case=$CASE port=$PORT extra=$EXTRA"
grep -m1 "ERROR: AddressSanitizer" "/tmp/pl_$CASE.log" | sed 's/^.*ERROR/ERROR/'
grep -m1 -E "WRITE of size|READ of size" "/tmp/pl_$CASE.log" || echo "access: none"
grep -m1 "SUMMARY:" "/tmp/pl_$CASE.log" || echo "SUMMARY: none"
grep -m1 -E "SEGV|ABRT|AddressSanitizer:DEADLYSIGNAL" "/tmp/pl_$CASE.log" | sed 's/0x[0-9a-f]*/0xADDR/' || true
grep -m1 -E "#0 |#1 |#2 |#3 |#4 " "/tmp/pl_$CASE.log" | sed 's/0x[0-9a-f]*/0xADDR/' || true
grep -m1 "EXIT=" "/tmp/pl_$CASE.log"
echo "-- beacons:"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "grep -a -o 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("   " + urllib.parse.unquote(l.strip()))'
