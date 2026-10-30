#!/usr/bin/env bash
# docs/75: XML parser custom-element window. Quarantine ON (run_asan_page.sh) unless RC=./run_nq.sh.
set -u
cd /home/<user>/wk
RC=${RC:-./run_asan_page.sh}
run() { # tag port query page
  TAG=$1; PORT=$2; Q=$3; PAGE=${4:-xml-ce.svg}
  pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
  ( cd /tmp/wkp && nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
  sleep 1
  "$RC" "http://127.0.0.1:$PORT/$PAGE?$Q" 25 > "/tmp/run_$TAG.log" 2>&1
  echo "=== $TAG $PAGE q=$Q"
  grep -m1 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer" "/tmp/run_$TAG.log" || echo "access: none"
  grep -m1 -E "^(READ|WRITE) of size|heap-use-after-free|SEGV" "/tmp/run_$TAG.log" || true
  grep -m1 -A 10 "ERROR: AddressSanitizer" "/tmp/run_$TAG.log" | sed -n '2,12p' || true
  grep -a "^EXIT=" "/tmp/run_$TAG.log" | tail -1
  grep -a -o "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("   B " + urllib.parse.unquote(l.strip()))'
  pkill -f "[h]ttp.server $PORT" 2>/dev/null
}
run E3 9777 "rm=0" evloop.html
run E4 9778 "rm=1" evloop.html
