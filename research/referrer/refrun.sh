#!/usr/bin/env bash
# Referrer-default probe runner. Kills only its OWN server port and its own MiniBrowser
# (another session may be running a page on the same box), quarantine OFF.
#   usage: refrun.sh <tag> <page-port> <res-port> <secs>
set -u
BOX=teo@<lab-ip>
TAG=${1:?}; PP=${2:?}; RP=${3:?}; SECS=${4:-20}
ROOT=$(cd "$(dirname "$0")" && pwd)
AO="detect_leaks=0:detect_stack_use_after_return=0:abort_on_error=1:symbolize=1:handle_abort=1:quarantine_size_mb=0:thread_local_quarantine_size_kb=0:max_free_fill_size=0"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "pkill -f '[r]efsrv.py --page-port $PP' ; true" >/dev/null 2>&1
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" "mkdir -p /tmp/wkp/referrer" >/dev/null 2>&1
scp -q "$ROOT/refsrv.py" "$BOX:/tmp/wkp/referrer/refsrv.py" || exit 2
ssh -o BatchMode=yes -o ConnectTimeout=8 "$BOX" \
  "cd /tmp/wkp/referrer && (setsid nohup python3 refsrv.py --page-port $PP --res-port $RP --out /tmp/ref_$TAG.log --seconds $((SECS+20)) > /tmp/ref_$TAG.srv 2>&1 &) ; sleep 1.5 ; curl -s -o /dev/null -w 'page=%{http_code} ' 'http://127.0.0.1:$PP/arm=a' ; curl -s -o /dev/null -w 'res=%{http_code}\n' 'http://127.0.0.1:$RP/res.png?arm=warm'"
ssh -o BatchMode=yes "$BOX" \
  "distrobox enter wk --no-tty -- bash -lc \"ASAN_OPTIONS='$AO' bash ~/wk/run_nq.sh 'http://localhost:$PP/arm=a' $SECS\"" \
  > "/tmp/L_ref_$TAG.log" 2>&1
ssh -o BatchMode=yes "$BOX" "pkill -f 'MiniBrowser http://localhost:$PP/' ; pkill -f '[r]efsrv.py --page-port $PP' ; true" >/dev/null 2>&1

echo "=== $TAG page=$PP res=$RP secs=$SECS"
echo "--- requests (Referer as seen by the server):"
ssh -o BatchMode=yes "$BOX" "cat /tmp/ref_$TAG.log" 2>/dev/null
echo "--- browser tail:"
grep -a "^EXIT=" "/tmp/L_ref_$TAG.log" | tail -1
