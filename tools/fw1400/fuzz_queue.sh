#!/usr/bin/env bash
# Sequential fuzz queue. Runs pools one after another and archives each run's output so the next
# pool's fuzz-w1..w6 directories do not overwrite it.
#
# Run detached: nohup ./fuzz_queue.sh > /dev/null 2>&1 &

set -u
cd "$HOME/wk" || exit 2
LOG=fuzz-queue.log

queue() {
    local fuzzer=$1 first=$2 last=$3 per=$4 workers=$5 label=$6
    echo "=== $label: $fuzzer $first..$last ($workers workers) $(date +%H:%M) ===" >> "$LOG"
    ./sweep_pool.sh "$fuzzer" "$first" "$last" "$per" "$workers" >> "$LOG" 2>&1
    mkdir -p "results/$label"
    mv fuzz-w1 fuzz-w2 fuzz-w3 fuzz-w4 fuzz-w5 fuzz-w6 "results/$label/" 2>/dev/null
    echo "=== $label done $(date +%H:%M) ===" >> "$LOG"
}

echo "=== queue start $(date +%H:%M) ===" >> "$LOG"
queue dom_fuzz.js           1201 5000 10 6 dom-1201-5000
queue parser_fuzz.js         201 1400 15 6 parser-201-1400
queue jsserializer_fuzz.js   201 1400 25 6 serializer-201-1400
echo "=== queue complete $(date +%H:%M) ===" >> "$LOG"
