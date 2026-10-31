#!/usr/bin/env bash
# docs/103 element probe: dump the disengaged std::optional<ImageBitmapBacking> element at
# ImageBitmapBacking::connect(), then let the process die and print si_addr.
#   usage: md8gdb.sh <tag> <port> "<query>" [secs]
# The page parks itself with delay= so the attach lands before the message is walked. ptrace_scope=0.
set -u
TAG=${1:?}; PORT=${2:?}; Q=${3:?}; SECS=${4:-45}
BOX=teo@<lab-ip>
ROOT=$(cd "$(dirname "$0")" && pwd)
PAGE=caps19.html
REMOTE=/tmp/md8_$TAG.sh
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0:max_malloc_fill_size=0"

scp -q "$ROOT/../fuzz-cssom/$PAGE" "$BOX:/tmp/wkp/$PAGE"
cat > "/tmp/$TAG.sh" <<'EOS'
#!/usr/bin/env bash
set -u
PORT=$1; Q=$2; SECS=$3; AO=$4; PAGE=$5
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
rm -f /tmp/srv$PORT.log
cd /tmp/wkp && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &)
sleep 1
( setsid nohup distrobox enter wk --no-tty -- bash -lc \
    "ASAN_OPTIONS='$AO' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/$PAGE?$Q' $SECS" \
    > /tmp/G_$PORT.log 2>&1 & )
PID=""
for i in $(seq 1 80); do
  PID=$(pgrep -n -f WebKitWebProcess || true)
  if [ -n "${PID:-}" ] && grep -aq "GET /ev?m=cap" "/tmp/srv$PORT.log" 2>/dev/null; then break; fi
  sleep 0.25
done
echo "=== pid=${PID:-none} port=$PORT q=$Q"
[ -n "${PID:-}" ] || { echo "no WebProcess"; exit 3; }
cat > /tmp/md8gdb.$PORT.cmd <<'EOF'
set pagination off
set confirm off
set print elements 0
handle SIGSEGV stop print
break WebCore::ImageBitmapBacking::connect
commands
silent
printf "ELEM=%p (rdi)\n", $rdi
x/4gx $rdi
printf "FIELD8="
p/x *(unsigned long*)((char*)$rdi+8)
printf "AT_FIELD8:\n"
x/4gx *(unsigned long*)((char*)$rdi+8)
printf "BT:\n"
bt 4
continue
end
continue
printf "SI_ADDR="
p/x $_siginfo._sifields._sigfault.si_addr
printf "REGS\n"
info registers rip rax rdi
printf "BT_AT_FAULT\n"
bt 8
detach
quit
EOF
timeout 90 gdb -q -batch -x /tmp/md8gdb.$PORT.cmd -p "$PID" 2>&1 | sed 's/^/  /'
sleep 1
echo "=== arm log:"
grep -aE "ERROR: AddressSanitizer|SUMMARY:|EXIT=" "/tmp/G_$PORT.log" | head -4 | sed 's/^/  /'
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
EOS
scp -q "/tmp/$TAG.sh" "$BOX:$REMOTE"
ssh -o BatchMode=yes "$BOX" "bash $REMOTE $PORT '$Q' $SECS '$AO' $PAGE" 2>&1
