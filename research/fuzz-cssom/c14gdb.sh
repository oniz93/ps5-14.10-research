#!/usr/bin/env bash
# docs/93 address probe: ASAN prints "SEGV on unknown address (pc ...)" with NO address on this
# kernel/build, so the planted pointer cannot be read out of the report. This script starts one
# caps14 arm with a page-side `delay=`, attaches gdb to the WebProcess while the page is parked,
# and prints si_addr plus the registers at the fault. ptrace_scope is 0 on the oracle.
# usage: c14gdb.sh <tag> <port> <secs> <query> [asan_extra]
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-60}; Q=${4:-}; EXTRA=${5:-}
DELAYQ="delay=12000"

# start the arm in the background (the page parks for 12 s before posting the message)
nohup bash /tmp/wkp/c14run.sh "$TAG" "$PORT" "$SECS" "$Q&$DELAYQ" "$EXTRA" > "/tmp/G_$TAG.log" 2>&1 &
RUN=$!
# wait for the WebProcess to exist and for the page to have parked
for i in $(seq 1 40); do
  PID=$(pgrep -n -f "WebKitWebProcess") || true
  if [ -n "${PID:-}" ] && grep -aq "GET /ev?m=pre" "/tmp/srv$PORT.log" 2>/dev/null; then break; fi
  sleep 0.5
done
echo "=== gdb attach: pid=${PID:-none} (tag=$TAG)"
if [ -z "${PID:-}" ]; then echo "no WebProcess found"; exit 3; fi
cat > /tmp/gdbcmd.$TAG <<'EOF'
set pagination off
set confirm off
set print elements 0
handle SIGSEGV stop print
continue
printf "SI_ADDR="
p/x $_siginfo._sifields._sigfault.si_addr
printf "REGS\n"
info registers rip rax rbx rcx rdx rsi rdi rbp rsp
printf "BT\n"
bt 6
detach
quit
EOF
timeout 40 gdb -q -batch -x /tmp/gdbcmd.$TAG -p "$PID" 2>&1 | sed 's/^/  /'
wait $RUN 2>/dev/null
echo "=== arm log tail:"
grep -aE "SEGV|SUMMARY|EXIT=" "/tmp/G_$TAG.log" | head -5 | sed 's/^/  /'
