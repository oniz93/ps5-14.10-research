#!/bin/bash
# Run the parser-window page against the local ASAN oracle on the build box, quarantine OFF,
# and print the sanitizer verdict plus the page's beacons.  Same contract as ../run-page.sh,
# except it copies a whole directory (the page needs p2.js, p8.js, s1.js as real files served
# over http; an inline copy would not go through HTMLScriptRunner's PendingScript path).
#
#   ./run-parser-window.sh <port> "<query-string>" <tag>
set -u
PORT=${1:?usage: run-parser-window.sh <port> "<query>" <tag>}
Q=${2:?}
TAG=${3:?}
DIR=$(cd "$(dirname "$0")/parser-window" && pwd)
BOX=teo@<lab-ip>
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "rm -rf /tmp/wkp && mkdir -p /tmp/wkp"
scp -q "$DIR"/index.html "$DIR"/p2.js "$DIR"/p8.js "$DIR"/s1.js "$BOX:/tmp/wkp/"
# Kill stale servers in their OWN ssh call: `pkill -f` matches the whole remote command line,
# and the start command below contains "http.server", so a combined call kills its own shell.
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server' ; true"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && ( setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 </dev/null & ) ; sleep 1; curl -s -o /dev/null -w 'srv=%{http_code}\n' http://127.0.0.1:$PORT/index.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd ~/wk && timeout 120 distrobox enter -n wk --no-tty -- bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/index.html?$Q' 60" > "/tmp/run_$TAG.log" 2>&1
echo "===== $TAG  q=$Q"
grep -m1 "ERROR: AddressSanitizer" "/tmp/run_$TAG.log" | sed 's/^.*ERROR/ERROR/'
grep -m1 -E "WRITE of size|READ of size" "/tmp/run_$TAG.log" || echo "access: none"
grep -m1 "#0 " "/tmp/run_$TAG.log" | sed 's/0x[0-9a-f]*/0xADDR/'
grep -m1 "SUMMARY:" "/tmp/run_$TAG.log" || echo "SUMMARY: none"
grep -m1 "is located" "/tmp/run_$TAG.log"
echo "-- beacons (sorted by the page's own sequence number; HTTP arrival order is not the JS order):"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "grep -a -o 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null | sed 's|GET /ev?m=||' \
  | python3 -c 'import sys,urllib.parse
rows=[]
for l in sys.stdin:
    s=urllib.parse.unquote(l.strip())
    try: rows.append((int(s.split(" ",1)[0]), s))
    except Exception: rows.append((10**9, s))
for _,s in sorted(rows): print("   " + s)'
