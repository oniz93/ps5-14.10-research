#!/usr/bin/env bash
# docs/109 — put the console's stack size on the oracle.  Wrapper around stkrun.sh that only sets
# STK_ULIMIT (KiB) and a per-arm port, so the *only* variable that changes between arms is the thread's
# stack size and the recursion depth.  One depth per run, one process per arm.
#
#   usage: ulrun.sh <tag> <port> <depth> <ulimit-kib|def> [secs]
#
#     ulrun.sh u512_8     8980 8    512
#     ulrun.sh u512_2000  8981 2000 512
#     ulrun.sh u1024_2000 8986 2000 1024
set -u
TAG=${1:?usage: ulrun.sh <tag> <port> <depth> <ulimit|def> [secs]}
PORT=${2:?}; D=${3:?}; UL=${4:-def}; SECS=${5:-25}
A_IDB='WebCore::createIDBKeyFromValue(JSC::JSGlobalObject&, JSC::JSValue, WTF::Vector<JSC::JSArray*, 0ul, WTF::CrashOnOverflow, 16ul, WTF::FastMalloc>&)'
if [ "$UL" = def ]; then
  STK_BT=1 bash ~/stkrun.sh "$TAG" "$PORT" "arm=widb&d=$D" "$SECS" "$A_IDB"
else
  STK_ULIMIT="$UL" STK_BT=1 bash ~/stkrun.sh "$TAG" "$PORT" "arm=widb&d=$D" "$SECS" "$A_IDB"
fi
