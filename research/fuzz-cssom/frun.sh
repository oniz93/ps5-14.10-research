#!/usr/bin/env bash
# docs/84 runner: one fuzz arm per spec, quarantine OFF (run_nq.sh), beacons scored from the server log.
# usage: frun.sh "<tag> <port> <secs> <query>" ["<tag> <port> <secs> <query>" ...]
# Each arm gets a FRESH port and a fresh `python3 -m http.server` after a pkill, so no two arms share a server.
set -u
PAGE=${PAGE:-fuzz.html}
cd /home/<user>/wk
for spec in "$@"; do
  TAG=${spec%% *}; rest=${spec#* }
  PORT=${rest%% *}; rest=${rest#* }
  SECS=${rest%% *}; Q=${rest#* }
  pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
  ( cd /tmp/wkp && nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
  sleep 1
  ./run_nq.sh "http://127.0.0.1:$PORT/$PAGE?$Q" "$SECS" > "/tmp/F_$TAG.log" 2>&1
  echo "=== $TAG  port=$PORT secs=$SECS  q=$Q"
  grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped|zapped" "/tmp/F_$TAG.log" || echo "  access: none"
  grep -a -m1 -B1 -A7 -E "ERROR: AddressSanitizer" "/tmp/F_$TAG.log" | sed 's/^/  | /' || true
  grep -a "^EXIT=" "/tmp/F_$TAG.log" | tail -1 | sed 's/^/  /'
  grep -a -oE "GET /ev\?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
ls=[urllib.parse.unquote(l.strip()) for l in sys.stdin]
print("  beacons=%d" % len(ls))
for l in ls:
    if l.startswith("done") or l.startswith("boot") or l.startswith("then") or l.startswith("tick"): print("   B " + l)
for l in [x for x in ls if x.startswith("census")]: print("   C " + l)
print("  -- last 4 op beacons --")
for l in [x for x in ls if "&op=" in x and not x.startswith("census")][-4:]: print("   B " + l)'
  pkill -f "[h]ttp.server $PORT" 2>/dev/null
done
