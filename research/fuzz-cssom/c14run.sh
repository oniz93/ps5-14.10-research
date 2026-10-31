#!/usr/bin/env bash
# docs/93 one-arm runner for caps14.html: fresh port, quarantine OFF, chosen malloc fill,
# beacons in arrival order + the ASAN frame + the EXIT line.
# usage: c14run.sh <tag> <port> <secs> <query> [asan_extra]
#   asan_extra examples: max_malloc_fill_size=0   (no fill: a fresh block keeps stale bytes)
#                        (empty)                 (default: fill 0xbe)
set -u
TAG=${1:?}; PORT=${2:?}; SECS=${3:-25}; Q=${4:-}; EXTRA=${5:-}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
if [ -n "$EXTRA" ]; then OPTS="$BASE:$EXTRA"; else OPTS="$BASE"; fi
pkill -f "[h]ttp.server $PORT" 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$OPTS' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/caps14.html?$Q' $SECS" > "/tmp/S_c14_$TAG.log" 2>&1 < /dev/null
echo "=== $TAG port=$PORT secs=$SECS q=$Q fill=${EXTRA:-default}"
echo "--- beacons (in order):"
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    s=l.strip().split("/ev?m=",1)[1]
    print("  " + urllib.parse.unquote(s))'
echo "--- abort:"
grep -a -m3 -E "ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|WTFCrashWithInfo|RELEASE_ASSERT|ASSERTION FAILED" "/tmp/S_c14_$TAG.log" || echo "  access: none"
grep -a -m1 -A14 -E "ERROR: AddressSanitizer" "/tmp/S_c14_$TAG.log" | sed 's/^/  | /' || true
echo "--- sites:"
grep -a -oE "ImageBitmap[A-Za-z]*\.cpp:[0-9]+|ByteArrayPixelBuffer\.cpp:[0-9]+|SerializedScriptValue\.cpp:[0-9]+|ImageBuffer\.cpp:[0-9]+|MessagePort\.cpp:[0-9]+|Optional\.h:[0-9]+" "/tmp/S_c14_$TAG.log" | sort | uniq -c | sed 's/^/  /'
echo "--- bytes of the ASAN fault:"
grep -a -oE "SEGV on unknown address 0x[0-9a-f]+|SEGV on unknown address \(pc" "/tmp/S_c14_$TAG.log" | head -2 | sed 's/^/  /'
grep -a -oE "0x[0-9a-f]{16}" "/tmp/S_c14_$TAG.log" | sort | uniq -c | sort -rn | head -6 | sed 's/^/  /'
grep -a "^EXIT=" "/tmp/S_c14_$TAG.log" | tail -1
pkill -f "[h]ttp.server $PORT" 2>/dev/null
