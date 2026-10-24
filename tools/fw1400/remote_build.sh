#!/usr/bin/env bash
# Run the ASAN build on the board so a dropped SSH link cannot kill it.
#
# Twice now a build has died for reasons unrelated to the code: once from swap thrash at -j5, and
# once because the SSH session carrying ninja timed out and took the process group with it. This
# script is meant to be started detached and left alone:
#
#   scp remote_build.sh teo@<board>:~/wk/ && ssh -f teo@<board> 'bash ~/wk/remote_build.sh'
#
# ssh -f backgrounds the *client* after authentication, so the remote process is reparented to
# init and survives a broken pipe. The build then reconnects to nothing: it just runs to the end
# and leaves its exit status in the log.
#
# Memory: the board has 7.5 GiB usable and each WebCore unified TU peaks at 1.5-3 GiB, so -j4 is
# already at the edge and -j5 provably thrashes. Keep JOBS at 3-4.

set -u

JOBS=${JOBS:-4}
DIR=${DIR:-$HOME/wk/WebKit}
LOG=${LOG:-$HOME/wk/build-asan.log}
NINJA=${NINJA:-WebKitBuild/ASAN}

cd "$DIR" || { echo "no build dir at $DIR" >&2; exit 2; }

# setsid detaches from the controlling terminal so SIGHUP on disconnect does not reach ninja.
{
    echo "=== resume $(date -Is) jobs=$JOBS target=$NINJA ==="
    setsid ninja -C "$NINJA" -j"$JOBS" >> "$LOG" 2>&1
    echo "EXIT=$?" >> "$LOG"
    echo "=== done $(date -Is) ==="
} </dev/null >/dev/null 2>&1 &

echo "started detached; tail -f $LOG"
