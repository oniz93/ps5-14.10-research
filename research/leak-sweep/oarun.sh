#!/usr/bin/env bash
# docs/99 one-arm runner for oobadj.html.  Kills only its OWN port (another session may be running a
# font corpus elsewhere on the board), serves from /tmp/wkp on a fresh port, quarantine OFF.
# usage: oarun.sh <tag> <port> <secs> [query]
set -u
BOX=teo@<lab-ip>
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}; PAGE=${5:-oobadj.html}; AOPT=${6:-}
ROOT=$(cd "$(dirname "$0")" && pwd)
SRC="$ROOT/$PAGE"
[ -f "$SRC" ] || SRC="$ROOT/../fuzz-cssom/$PAGE"
for d in canvas-alias leak-sweep; do [ -f "$SRC" ] || SRC="$ROOT/../$d/$PAGE"; done   # pages live in sibling sets

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1
sleep 0.2
[ -f "$SRC" ] || { echo "no such page: $PAGE" >&2; exit 2; }
scp -q "$SRC" "$BOX:/tmp/wkp/$PAGE"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &) ; sleep 1 ; curl -s -o /dev/null -w 'srv=%{http_code}\n' 'http://127.0.0.1:$PORT/$PAGE'"
ssh -o BatchMode=yes "$BOX" \
  "distrobox enter wk --no-tty -- bash -lc \"${AOPT:+env ASAN_OPTIONS=$AOPT }bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/$PAGE?$Q' $SECS\"" \
  > "/tmp/S_oa_$TAG.log" 2>&1

echo "=== $TAG port=$PORT q=$Q"
ssh -o BatchMode=yes "$BOX" "grep -aoE '(GET|POST) /ev\?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null \
  | sed -E 's@^(GET|POST) /ev\?m=@@' \
  | python3 -c 'import sys, urllib.parse
for l in sys.stdin: print(urllib.parse.unquote(l.strip()))'
if grep -aqE "ERROR: AddressSanitizer|WTFCrashWithInfo|CRASHED" "/tmp/S_oa_$TAG.log"; then
  grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY|CRASHED" "/tmp/S_oa_$TAG.log" | sed 's/^/  /'
else
  echo "  access: none"
fi
grep -a "^EXIT=" "/tmp/S_oa_$TAG.log" | tail -1
ssh -o BatchMode=yes "$BOX" "pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1
