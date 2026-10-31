#!/usr/bin/env bash
# Capture the OTF that WebKit's SVG-font writer hands to FreeType, for one corpus arm.
# The WebProcess is stopped at FT_New_Memory_Face (single caller in the drop:
# FontCustomPlatformDataFreeType.cpp:144) and $rsi..$rsi+$rdx is written to /tmp/otf/<tag>_NN.bin.
# The page is parked with ?delay= so the attach lands before the first arm runs.
#   usage: otfgdb.sh <tag> <port> "<query>" [delay_ms] [secs]
set -u
TAG=${1:?}; PORT=${2:?}; Q=${3:?}; DELAY=${4:-20000}; SECS=${5:-90}
BOX=teo@<lab-ip>
ROOT=$(cd "$(dirname "$0")" && pwd)
REMOTE=/tmp/otfgdb_$TAG.sh
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"

ssh -o BatchMode=yes "$BOX" "rm -rf /tmp/otf; mkdir -p /tmp/otf" || exit 2
scp -q "$ROOT/corpus.html" "$BOX:/tmp/wkp/sf/corpus.html" || exit 2
mkdir -p "$ROOT/../../data/otf-dump/$TAG"

cat > "/tmp/otf_$TAG.gdb.py" <<'EOS'
import gdb, os
TAG = os.environ.get("OTFTAG", "x")

class Dump(gdb.Breakpoint):
    n = 0
    def stop(self):
        try:
            base = int(gdb.parse_and_eval("$rsi"))
            size = int(gdb.parse_and_eval("$rdx"))
        except Exception as e:
            print("ARGSFAIL %s" % e)
            return False
        Dump.n += 1
        path = "/tmp/otf/%s_%02d.bin" % (TAG, Dump.n)
        try:
            mem = gdb.selected_inferior().read_memory(base, size).tobytes()
        except Exception as e:
            print("READFAIL %s base=0x%x size=%d err=%s" % (path, base, size, e))
            return False
        with open(path, "wb") as f:
            f.write(mem)
        print("DUMP %s base=0x%x size=%d head=%s" % (path, base, size, mem[:4].hex()))
        gdb.execute("bt 3")
        return False

Dump("*FT_New_Memory_Face")
print("BP_READY")
EOS

cat > "/tmp/$TAG.sh" <<'EOS'
#!/usr/bin/env bash
set -u
PORT=$1; Q=$2; DELAY=$3; SECS=$4; AO=$5; TAG=$6
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
rm -f /tmp/srv$PORT.log
cd /tmp/wkp/sf || exit 2
( setsid nohup python3 -m http.server $PORT > /tmp/srv$PORT.log 2>&1 & )
sleep 1
T0=$(date +%s.%N)
( setsid nohup distrobox enter wk --no-tty -- bash -lc \
    "ASAN_OPTIONS='$AO' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/corpus.html?delay=$DELAY&$Q' $SECS" \
    > /tmp/G_$PORT.log 2>&1 & )
MB=""
for i in $(seq 1 200); do
  MB=$(pgrep -f "MiniBrowser http://127.0.0.1:$PORT/" | head -1 || true)
  [ -n "${MB:-}" ] && break
  sleep 0.1
done
PID=""
for i in $(seq 1 200); do
  if [ -n "${MB:-}" ]; then
    PID=$(pgrep -P "$MB" -f WebKitWebProcess 2>/dev/null | head -1 || true)
  fi
  [ -n "${PID:-}" ] && break
  # fall back to the newest WebProcess only if no parent match ever appears
  [ $i -gt 60 ] && PID=$(pgrep -n -f WebKitWebProcess 2>/dev/null || true)
  [ -n "${PID:-}" ] && break
  sleep 0.1
done
echo "=== tag=$TAG port=$PORT q=$Q delay=$DELAY secs=$SECS"
echo "  MiniBrowser=${MB:-none} WebProcess=${PID:-none} ppid=$(awk '/^PPid/{print $2}' /proc/${PID:-0}/status 2>/dev/null)"
[ -n "${PID:-}" ] || { echo "no WebProcess"; exit 3; }
sleep 0.5
grep -a -c "GET /corpus.html" /tmp/srv$PORT.log | sed 's/^/  corpus requests before attach: /'
A0=$(date +%s.%N)
timeout $((SECS + 60)) gdb -q -batch -p "$PID" \
  -ex "set pagination off" -ex "set confirm off" -ex "set height 0" -ex "set width 0" \
  -ex "info sharedlibrary freetype" \
  -ex "source /tmp/otf_$TAG.gdb.py" -ex "continue" 2>&1 | sed 's/^/  /'
A1=$(date +%s.%N)
awk -v a="$A0" -v b="$A1" 'BEGIN{printf "  attach+dump wall: %.1f s\n", b-a}'
awk -v a="$T0" -v b="$A0" 'BEGIN{printf "  launch->attach start: %.1f s\n", b-a}'
echo "=== dumps:"
ls -l /tmp/otf/ | sed 's/^/  /'
echo "=== arm log (head):"
grep -a -m6 -E "ERROR: AddressSanitizer|SUMMARY:|EXIT=|BOOT" /tmp/G_$PORT.log | sed 's/^/  /'
echo "=== beacons:"
grep -ao "GET /ev?m=[^ ]*" /tmp/srv$PORT.log | python3 -c 'import sys,urllib.parse
for l in sys.stdin: print("  " + urllib.parse.unquote(l.strip().split("/ev?m=",1)[1]))' | head -20
pkill -f "[h]ttp.server $PORT" 2>/dev/null; true
EOS

scp -q "/tmp/$TAG.sh" "$BOX:$REMOTE" || exit 2
scp -q "/tmp/otf_$TAG.gdb.py" "$BOX:/tmp/otf_$TAG.gdb.py" || exit 2
ssh -o BatchMode=yes "$BOX" "OTFTAG=$TAG bash $REMOTE $PORT '$Q' $DELAY $SECS '$AO' $TAG" 2>&1

# bring the dumps and the gdb transcript back
ssh -o BatchMode=yes "$BOX" "cd /tmp/otf && tar cf - *.bin 2>/dev/null" | tar xf - -C "$ROOT/../../data/otf-dump/$TAG" 2>/dev/null
ls -l "$ROOT/../../data/otf-dump/$TAG" | sed 's/^/  local: /'
