#!/usr/bin/env bash
# Parallel fuzz pool: shards a seed range across workers, each with its own output dir and beacon
# port, then aggregates.
#
# Why: a single MiniBrowser run is effectively single-threaded, so the serial runner left the board
# at load ~1.7 of 12 threads. Six workers cut a 1200-seed sweep from ~100 minutes to ~20.
#
#   ./sweep_pool_img.sh <fuzzer.js> <first> <last> <seconds> <workers>
#
# Everything is inside the distrobox container; run this from ~/wk.

set -u
FUZZER=${1:-dom_fuzz.js}
FIRST=${2:-1}
LAST=${3:-300}
PER=${4:-10}
WORKERS=${5:-6}
BASE_PORT=${BASE_PORT:-8300}

cd "$HOME/wk" || exit 2
TOTAL=$((LAST - FIRST + 1))
CHUNK=$(( (TOTAL + WORKERS - 1) / WORKERS ))

echo "pool(img): $FUZZER seeds $FIRST..$LAST, $WORKERS workers, ~$CHUNK seeds each, ${PER}s ceiling"

pids=""
w=1
a=$FIRST
while [ "$a" -le "$LAST" ]; do
    b=$((a + CHUNK - 1))
    [ "$b" -gt "$LAST" ] && b=$LAST
    port=$((BASE_PORT + w))
    # BEACON_PORT is the name run_fuzz.sh reads; passing PORT silently made every worker contend
    # for 8123 and five of six died on "Address already in use".
    # TAG decides the output directory (fuzz-$TAG). It must differ from the generic pool's "w$w"
    # or both pools write into fuzz-w1.. and destroy each other's beacon logs.
    TAG="iw$w" BEACON_PORT="$port" FUZZER="$FUZZER" \
        nohup ./run_image_fuzz.sh "$a" "$b" "$PER" > "fuzz-iw$w.log" 2>&1 &
    pids="$pids $!"
    echo "  worker $w: seeds $a..$b port $port log fuzz-iw$w.log"
    w=$((w + 1))
    a=$((b + 1))
done

for p in $pids; do wait "$p"; done

# Aggregate. "completed" is the only number that means anything: it counts seeds whose page
# reached its DONE beacon. A seed that never completed proves nothing either way.
done_count=0
clean_sum=0
crashes=0
incomplete=0
for f in fuzz-iw*.log; do
    [ -f "$f" ] || continue
    line=$(grep -h "^done:" "$f" | tail -1)
    [ -z "$line" ] && { echo "worker log $f has no summary (died?)"; continue; }
    c=$(echo "$line" | sed -n 's/.*clean=\([0-9]*\).*/\1/p')
    k=$(echo "$line" | sed -n 's/.*completed=\([0-9]*\).*/\1/p')
    x=$(echo "$line" | sed -n 's/.*asan_crashes=\([0-9]*\).*/\1/p')
    i=$(echo "$line" | sed -n 's/.*incomplete=\([0-9]*\).*/\1/p')
    clean_sum=$((clean_sum + ${c:-0}))
    done_count=$((done_count + ${k:-0}))
    crashes=$((crashes + ${x:-0}))
    incomplete=$((incomplete + ${i:-0}))
done

echo
echo "POOL RESULT: completed=$done_count clean=$clean_sum asan_crashes=$crashes incomplete=$incomplete"
for d in fuzz-iw*/; do [ -d "$d" ] || continue; [ -f "$d/crashes.txt" ] && echo "crashes in $d: $(tr '\n' ' ' < "$d/crashes.txt")"; done
