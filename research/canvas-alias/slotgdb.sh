#!/usr/bin/env bash
# docs/112 — give docs/103's canvas negative an address.
#
# Runs the c043b/docs/103 trigger (canvasfield.html) on the ASAN oracle with quarantine OFF, attaches gdb to
# that run's own WebProcess *before* the trigger (the page waits on /gate.txt), records the freed
# CanvasRenderingContext2D chunk A at its destructor, confirms the free at WTF::fastFree(A), then records every
# later allocation whose request lands in A's ASAN size class and whether it returns A, and finally what is at A
# when the stale wrapper is used.  Full gdb output is kept at /tmp/GDB_<port>.log on the box and echoed.
#
#   usage: slotgdb.sh <tag> <port> "<query>" [secs]
#
# One variable per arm: the query string alone decides spray / no-spray / cross-type.
set -u
TAG=${1:?}; PORT=${2:?}; Q=${3:?}; SECS=${4:-160}
BOX=teo@<lab-ip>
ROOT=$(cd "$(dirname "$0")" && pwd)
PAGE=canvasfield.html
REMOTE=/tmp/slot_$TAG.sh
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0:max_malloc_fill_size=0"

scp -q "$ROOT/$PAGE" "$BOX:/tmp/wkp/$PAGE"
scp -q "$ROOT/slotwatch.py" "$BOX:/tmp/slotwatch.py"
cat > "/tmp/$TAG.sh" <<'EOS'
#!/usr/bin/env bash
set -u
PORT=$1; Q=$2; SECS=$3; AO=$4; PAGE=$5
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
rm -f /tmp/srv$PORT.log /tmp/GDB_$PORT.log
echo wait > /tmp/wkp/gate.txt
cd /tmp/wkp && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &)
sleep 1
( setsid nohup distrobox enter wk --no-tty -- bash -lc \
    "ASAN_OPTIONS='$AO' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/$PAGE?$Q' $SECS" \
    > /tmp/G_$PORT.log 2>&1 & )
PID=""
for i in $(seq 1 160); do
  UI=$(pgrep -f "MiniBrowser http://127.0.0.1:$PORT" | head -1 || true)
  if [ -n "${UI:-}" ]; then
    PID=$(pgrep -P "$UI" -f WebKitWebProcess | head -1 || true)
    [ -n "${PID:-}" ] || PID=$(pgrep -n -f WebKitWebProcess || true)
  fi
  if [ -n "${PID:-}" ] && [ -s "/tmp/srv$PORT.log" ]; then break; fi
  sleep 0.25
done
echo "=== tag=$PORT pid=${PID:-none} ui=${UI:-none} q=$Q"
[ -n "${PID:-}" ] || { echo "no WebProcess"; pkill -f "[h]ttp.server $PORT" 2>/dev/null; exit 3; }

cat > /tmp/slotgdb.$PORT.cmd <<'EOF'
set pagination off
set confirm off
set debuginfod enabled off
set breakpoint pending on
set print elements 0
handle SIGSEGV stop print nopass

source /tmp/slotwatch.py

info break
shell echo go > /tmp/wkp/gate.txt
continue
printf "FAULT si_addr="
p/x $_siginfo._sifields._sigfault.si_addr
printf "SLOT A=%p\n", $A
printf "SLOT shadow="
x/1xb (((unsigned long)$A >> 3) + 0x7fff8000)
printf "SLOT first32:\n"
x/4gx $A
printf "REGS\n"
info registers rip rax rbx rdi rsi
printf "FAULT_BT\n"
bt 12
printf "SLOT occupant:\n"
info symbol *(void**)$A
detach
quit
EOF
timeout 220 gdb -q -batch -x /tmp/slotgdb.$PORT.cmd -p "$PID" > /tmp/GDB_$PORT.log 2>&1
echo "=== gdb (slot lines):"
grep -aE "CTXDTOR A=|FREED-A|FREE-RETURNED|WATCH installed|WROTE-A|FAULT si|SLOT |FAULT_BT|^  #|in WebCore|in WTF|SUMMARY" /tmp/GDB_$PORT.log | head -100 | sed 's/^/  /'
echo "=== page beacons:"
grep -aoE '(GET|POST) /ev\?m=[^ ]*' "/tmp/srv$PORT.log" 2>/dev/null | sed -E 's@^(GET|POST) /ev\?m=@@' \
  | python3 -c 'import sys, urllib.parse
for l in sys.stdin: print(urllib.parse.unquote(l.strip()))'
echo "=== arm log:"
grep -aE "ERROR: AddressSanitizer|SUMMARY:|EXIT=|CRASHED" "/tmp/G_$PORT.log" | head -5 | sed 's/^/  /'
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
EOS
scp -q "/tmp/$TAG.sh" "$BOX:$REMOTE"
ssh -o BatchMode=yes "$BOX" "bash $REMOTE $PORT '$Q' $SECS '$AO' $PAGE" 2>&1
