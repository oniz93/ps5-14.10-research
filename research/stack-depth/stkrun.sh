#!/usr/bin/env bash
# docs/108 runner — ONE arm per process load, gdb attached to that run's own WebProcess, $rsp per breakpoint hit.
# Runs ON the oracle (teo@<lab-ip>); the page is served from /tmp/wkp by a fresh server on a fresh port.
#
#   usage: stkrun.sh <tag> <port> "<query>" <secs> [<gdb-symbol-signature> ...]
#
# Each spec is a FULL C++ signature (as printed by `nm -C`), which gdb resolves through the .so's symbol table
# without DWARF (the ASAN build's .debug_info is unreadable through a host attach, but .symtab is fine).
# No spec = page-only arm (no gdb attach).  The page parks on /go.txt, which is created only after gdb has
# attached and its breakpoints are set, so no arm can run before the instrument is armed.
set -u
TAG=${1:?usage: stkrun.sh <tag> <port> "<query>" <secs> [bp ...]}; PORT=${2:?}; Q=${3:?}; SECS=${4:-40}; shift 4
BPS=("$@")

[ -f "/tmp/srv$PORT.pid" ] && kill "$(cat "/tmp/srv$PORT.pid")" 2>/dev/null
rm -f /tmp/wkp/go.txt "/tmp/srv$PORT.log" "/tmp/G_$TAG.log" "/tmp/R_$TAG.log"
cd /tmp/wkp || exit 1
setsid nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
echo $! > "/tmp/srv$PORT.pid"
sleep 1

BEFORE=" $(pgrep -f WebKitWebProcess | tr '\n' ' ') "
INNER="bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/stack.html?$Q' $SECS"
# STK_ULIMIT=<KiB> shrinks RLIMIT_STACK for the whole browser process: glibc derives the default thread
# stack size from it, which is exactly the console's situation (WTF calls no setstacksize on this port).
[ -n "${STK_ULIMIT:-}" ] && INNER="ulimit -s $STK_ULIMIT; $INNER"
( setsid nohup distrobox enter wk --no-tty -- bash -lc "$INNER" > "/tmp/R_$TAG.log" 2>&1 & )

PID=""
for i in $(seq 1 240); do
  P=""
  for p in $(pgrep -f WebKitWebProcess 2>/dev/null || true); do
    case "$BEFORE" in *" $p "*) continue ;; esac
    P=$p
  done
  if [ -n "${P:-}" ] && grep -aq "GET /ev?m=boot" "/tmp/srv$PORT.log" 2>/dev/null; then PID=$P; break; fi
  sleep 0.25
done
echo "=== $TAG  pid=${PID:-none}  port=$PORT  q=$Q  secs=$SECS  bps=${#BPS[@]}  ulimit=${STK_ULIMIT:-default}"
[ -n "${PID:-}" ] || { echo "no WebProcess"; tail -6 "/tmp/R_$TAG.log" 2>/dev/null; exit 3; }

if [ "${#BPS[@]}" -gt 0 ]; then
  {
    echo "set pagination off"
    echo "set confirm off"
    echo "set print elements 0"
    echo "set \$n = 0"
    for b in "${BPS[@]}"; do
      echo "break '$b'"
      echo "commands"
      echo "silent"
      echo "set \$n = \$n + 1"
      echo 'printf "H %d t=%d bp=%d rsp=%p\n", $n, $_thread, $_hit_bpnum, $rsp'
      echo "continue"
      echo "end"
    done
    echo "continue"
    # STK_BT=1: after the top-level continue, gdb only gets control back on a stop that no breakpoint
    # command list handled (the fault), so these lines are the crash transcript.
    [ -n "${STK_BT:-}" ] && { echo 'printf "STOP rsp=%p pc=%p thread=%d\n", $rsp, $pc, $_thread'; echo "bt 5"; }
  } > "/tmp/stk_$TAG.cmd"
  ( setsid nohup timeout 200 gdb -q -batch -x "/tmp/stk_$TAG.cmd" -p "$PID" > "/tmp/G_$TAG.log" 2>&1 & )
  sleep 7
  echo "--- gdb attach:"
  grep -aE "^Breakpoint|^[0-9]+ +breakpoint|No symbol|error" "/tmp/G_$TAG.log" 2>/dev/null | head -8 | sed 's/^/  /'
fi

touch /tmp/wkp/go.txt

for i in $(seq 1 $((SECS + 40))); do
  grep -aq "GET /ev?m=done" "/tmp/srv$PORT.log" 2>/dev/null && break
  sleep 1
done
sleep 3

echo "--- beacons:"
grep -aoE "GET /ev\?m=[^ ]*" "/tmp/srv$PORT.log" 2>/dev/null | sed 's|GET /ev?m=||' | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("  B "+urllib.parse.unquote(l.strip()))'
cat "/proc/$PID/maps" > "/tmp/maps_$TAG.txt" 2>/dev/null && echo "--- maps: $(wc -l < "/tmp/maps_$TAG.txt") lines -> /tmp/maps_$TAG.txt"
echo "--- run tail:"
grep -aE "EXIT=|ERROR: AddressSanitizer|SUMMARY:|stack-overflow" "/tmp/R_$TAG.log" 2>/dev/null | tail -3 | sed 's/^/  /'
if [ -s "/tmp/G_$TAG.log" ]; then
  echo "--- gdb: $(grep -ac '^H ' "/tmp/G_$TAG.log" 2>/dev/null || echo 0) hits"
  grep -a '^H ' "/tmp/G_$TAG.log" 2>/dev/null | head -3 | sed 's/^/  /'
  echo "  ... last: $(grep -a '^H ' "/tmp/G_$TAG.log" 2>/dev/null | tail -1)"
  echo "--- faults:"
  grep -aE "Program received|SIGSEGV|AddressSanitizer|stack-overflow|Cannot access memory" "/tmp/G_$TAG.log" 2>/dev/null | head -3 | sed 's/^/  /'
fi
[ -f "/tmp/srv$PORT.pid" ] && kill "$(cat "/tmp/srv$PORT.pid")" 2>/dev/null
exit 0
