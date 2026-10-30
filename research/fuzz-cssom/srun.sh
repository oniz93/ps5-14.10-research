#!/usr/bin/env bash
# docs/85 runner: one seq.html arm per spec, FRESH port per arm, scored from the beacon log.
# usage: PAGE=seq.html RUN=nq srun.sh "<tag> <port> <secs> <query>" [...]
#   RUN=nq   -> run_nq.sh        (allocator quarantine OFF: for reclaim/reuse experiments, the sweep)
#   RUN=asan -> run_asan_page.sh (quarantine ON: only for confirming that a bug exists)
# The ASAN toolchain (libasan.so.8, xvfb-run) lives inside the distrobox container `wk`, not on the
# host, so the runner is invoked through `distrobox enter wk`.  The HTTP server stays on the host:
# the container shares the host's network namespace, so 127.0.0.1 is the same stack.
# Each arm gets a fresh `python3 -m http.server` after a pkill, so no two arms share a server.
set -u
PAGE=${PAGE:-seq.html}
RUN=${RUN:-nq}
case "$RUN" in
  nq)   SCRIPT=run_nq.sh ;;
  asan) SCRIPT=run_asan_page.sh ;;
  *) echo "RUN must be nq or asan" >&2; exit 2 ;;
esac
for spec in "$@"; do
  TAG=${spec%% *}; rest=${spec#* }
  PORT=${rest%% *}; rest=${rest#* }
  SECS=${rest%% *}; Q=${rest#* }
  URL="http://127.0.0.1:$PORT/$PAGE?$Q"
  pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
  ( cd /tmp/wkp && nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 & )
  sleep 1
  distrobox enter wk --no-tty -- bash -lc "bash ~/wk/$SCRIPT '$URL' $SECS" > "/tmp/S_$TAG.log" 2>&1
  echo "=== $TAG  run=$RUN port=$PORT secs=$SECS  q=$Q"
  grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|RELEASE_ASSERT|Zapped|zapped" "/tmp/S_$TAG.log" || echo "  access: none"
  grep -a -m1 -B2 -A8 -E "ERROR: AddressSanitizer" "/tmp/S_$TAG.log" | sed 's/^/  | /' || true
  grep -a "^EXIT=" "/tmp/S_$TAG.log" | tail -1 | sed 's/^/  /'
  grep -a -oE "GET /ev\?m=[^ ]*" "/tmp/srv$PORT.log" | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
ls=[urllib.parse.unquote(l.strip()) for l in sys.stdin]
print("  beacons=%d" % len(ls))
for l in ls:
    if l.startswith("done") or l.startswith("boot") or l.startswith("then") or l.startswith("tick") \
       or l.startswith("cal") or l.startswith("gcprobe") or l.startswith("decoys"): print("   B " + l)
cs=[x for x in ls if x.startswith("census") and not x.endswith("n=0&e=0")]
for l in cs: print("   C " + l)
print("  -- last 4 op beacons --")
for l in [x for x in ls if "&op=" in x and not x.startswith("census") and not x.startswith("done")][-4:]: print("   B " + l)'
  pkill -f "[h]ttp.server $PORT" 2>/dev/null
done
