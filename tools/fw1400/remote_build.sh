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

JOBS=${JOBS:-6}
DIR=${DIR:-$HOME/wk/WebKit}
LOG=${LOG:-$HOME/wk/build-asan.log}
NINJA=${NINJA:-WebKitBuild/ASAN}

cd "$DIR" || { echo "no build dir at $DIR" >&2; exit 2; }

# The toolchain (ninja, gcc, cmake) lives inside the distrobox container, not on the host, so the
# build must run there. Calling ninja directly fails with 127 "No such file or directory".
CONTAINER=${CONTAINER:-wk}
if command -v distrobox >/dev/null; then
    RUNNER="distrobox enter -n $CONTAINER --no-tty -- bash -lc"
else
    RUNNER="bash -lc"
fi

# Three layers, because this build has now been killed twice by things other than the code:
#   setsid          - detaches from the controlling terminal, so SIGHUP on disconnect misses it
#   systemd-inhibit - blocks idle/sleep for the duration, in case a power profile asks anyway
#   KillUserProcesses=no (set by bc250-fix.sh) - stops logind reaping the build on SSH logout
# Best-effort only: systemd-inhibit requires root or interactive auth for sleep/in idle, so as a
# normal user it fails - and making it mandatory meant it took ninja down with it (EXIT=1 with
# nothing compiled). Probe it with a trivial command first and fall back to no inhibit; the masked
# sleep targets from bc250-fix.sh are the layer that actually guarantees this.
INHIBIT=""
if command -v systemd-inhibit >/dev/null; then
    if systemd-inhibit --what=idle:sleep:shutdown --mode=block true >/dev/null 2>&1; then
        INHIBIT="systemd-inhibit --what=idle:sleep:shutdown --mode=block --who=webkit-asan --why=build"
    else
        echo "note: systemd-inhibit unavailable unprivileged; relying on masked sleep targets"
    fi
fi

{
    echo "=== resume $(date -Is) jobs=$JOBS target=$NINJA ==="
    setsid $INHIBIT $RUNNER "ninja -C $NINJA -j$JOBS" >> "$LOG" 2>&1
    echo "EXIT=$?" >> "$LOG"
    echo "=== done $(date -Is) ==="
} </dev/null >/dev/null 2>&1 &

echo "started detached; tail -f $LOG"
