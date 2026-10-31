#!/usr/bin/env bash
# scratch probe runner (vertical text orientation): fresh port, quarantine off.
set -u
PORT=${1:-8892}; SECS=${2:-25}; PAGE=${3:-probe.html}
BASE="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"
fuser -k "$PORT"/tcp 2>/dev/null; sleep 0.3
cd /tmp/wkp || exit 2
nohup python3 -m http.server "$PORT" > "/tmp/srv$PORT.log" 2>&1 &
sleep 1
distrobox enter wk --no-tty -- bash -lc "ASAN_OPTIONS='$BASE' bash ~/wk/run_nq.sh 'http://127.0.0.1:$PORT/$PAGE' $SECS" > "/tmp/L_probe$PORT.log" 2>&1 < /dev/null
grep -ao "GET /ev?m=[^ ]*" "/tmp/srv$PORT.log" | python3 -c 'import sys,urllib.parse
for l in sys.stdin:
    print(urllib.parse.unquote(l.strip().split("/ev?m=",1)[1]))'
grep -a -m3 -E "ERROR: AddressSanitizer|EXIT=" "/tmp/L_probe$PORT.log"
fuser -k "$PORT"/tcp 2>/dev/null
