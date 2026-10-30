#!/usr/bin/env bash
# docs/76 runner: CachedString cell-class differential. Quarantine OFF (run_nq.sh) so a freed slot is reusable.
# usage: runs.sh "<tag> <port> <query>" ["<tag> <port> <query>" ...]
set -u
cd /home/<user>/wk
RC=${RC:-./run_nq.sh}
PAGE=${PAGE:-class-wall.html}
SECS=${SECS:-30}
for spec in "$@"; do
  TAG=${spec%% *}
  rest=${spec#* }
  PORT=${rest%% *}
  Q=${rest#* }
  pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
  ( cd /tmp/wkp && nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
  sleep 1
  "$RC" "http://127.0.0.1:$PORT/$PAGE?$Q" "$SECS" > "/tmp/run_$TAG.log" 2>&1
  echo "=== $TAG  $PAGE?$Q"
  grep -m1 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT" "/tmp/run_$TAG.log" || echo "access: none"
  grep -m1 -E "^(READ|WRITE) of size|heap-use-after-free|SEGV|stack-overflow" "/tmp/run_$TAG.log" || true
  grep -a "^EXIT=" "/tmp/run_$TAG.log" | tail -1
  grep -a -o "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("   B " + urllib.parse.unquote(l.strip()))'
  pkill -f "[h]ttp.server $PORT" 2>/dev/null
done
