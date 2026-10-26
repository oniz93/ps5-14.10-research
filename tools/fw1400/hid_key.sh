#!/bin/bash
# Shell implementation of the keyboard bridge protocol, writing straight to /dev/hidg0.
#
# Why shell: the Pi Zero runs DietPi minimal with no Python, and installing it would mean waiting for
# a dist-upgrade to release the apt lock. A keypress is 8 bytes written twice, which bash does fine.
#
# Invoked per command over SSH, so there is no state between calls: HOLD/RELEASE cannot work this way
# and are rejected rather than silently doing something wrong. PRESS, SEQUENCE and ALLUP are enough to
# drive the Guide (Enter = OK, Escape = back, F3 = Options).
#
# CRITICAL: the device is opened ONCE and held open across the press and the release.
#
# Writing a report with `printf > /dev/hidg0` opens the file, queues a USB request and closes again.
# f_hid frees its request on close, and the host only polls an interrupt IN endpoint every bInterval
# (4 ms here) - so a report queued microseconds before the close is cancelled before the console ever
# reads it. The failure is silent: every write returns success and nothing happens on screen. Measured
# against a real keyboard on the console: a real Enter dismisses a system dialog, ours did not.
#
#   hid_key.sh PING | STATUS | "PRESS enter 120" | "SEQUENCE up,enter 150" | ALLUP

DEV=/dev/hidg0

code_for() {
    case "$1" in
        enter) echo '\x28' ;;
        escape|esc) echo '\x29' ;;
        backspace) echo '\x2a' ;;
        tab) echo '\x2b' ;;
        space) echo '\x2c' ;;
        home) echo '\x4a' ;;
        delete) echo '\x4c' ;;
        end) echo '\x4d' ;;
        right) echo '\x4f' ;;
        left) echo '\x50' ;;
        down) echo '\x51' ;;
        up) echo '\x52' ;;
        f1) echo '\x3a' ;;
        f2) echo '\x3b' ;;
        f3) echo '\x3c' ;;
        f4) echo '\x3d' ;;
        *) echo "" ;;
    esac
}

open_dev() {
    # exec keeps fd 3 open for the whole command, so no report is cancelled mid-flight.
    if ! exec 3>"$DEV" 2>/dev/null; then
        echo "ERR cannot open $DEV"
        exit 3
    fi
}

close_dev() {
    # Give the host one full polling interval to collect the final release report.
    sleep 0.08
    exec 3>&- 2>/dev/null || true
}

# Build an 8-byte report: modifiers, reserved, then up to six keycodes.
send_report() {
    local out='\x00\x00' i c
    for i in 1 2 3 4 5 6; do
        c="$(code_for "${!i}")"
        if [ -n "$c" ]; then out="$out$c"; else out="$out"'\x00'; fi
    done
    if ! printf "$out" >&3 2>/dev/null; then
        echo "ERR write failed"
        return 1
    fi
    return 0
}

all_up() { printf '\x00\x00\x00\x00\x00\x00\x00\x00' >&3 2>/dev/null || true; }

# Accept both `hid_key.sh PRESS enter 120` and `hid_key.sh "PRESS enter 120"`: the SSH client sends
# the whole line as one argument unless it is deliberately unquoted, and treating those two forms
# differently turned every command into "ERR unknown command".
set -- $*
cmd="${1:-}"
shift 2>/dev/null

case "$cmd" in
    PING|ping)
        echo PONG
        ;;
    STATUS|status)
        if [ -e "$DEV" ]; then
            # "not attached" is the normal state until the cable goes into the console.
            state=$(cat /sys/class/udc/*/state 2>/dev/null | head -1)
            echo "READY udc=${state:-unknown}"
        else
            echo "ERR no $DEV"
        fi
        ;;
    PRESS|press)
        key="$1"; ms="${2:-120}"
        c="$(code_for "$key")"
        [ -z "$c" ] && { echo "ERR unknown key"; exit 2; }
        open_dev
        send_report "$c" || exit 3
        sleep "$(awk -v m="$ms" 'BEGIN{printf "%.3f", m/1000}')"
        all_up
        close_dev
        echo OK
        ;;
    SEQUENCE|sequence)
        keys="$1"; gap="${2:-150}"
        IFS=',' read -ra list <<< "$keys"
        open_dev
        for k in "${list[@]}"; do
            c="$(code_for "$k")"
            [ -z "$c" ] && { echo "ERR unknown key $k"; exit 2; }
            send_report "$c" || exit 3
            sleep 0.12
            all_up
            sleep "$(awk -v m="$gap" 'BEGIN{printf "%.3f", m/1000}')"
        done
        close_dev
        echo OK
        ;;
    ALLUP|allup)
        open_dev
        all_up
        close_dev
        echo OK
        ;;
    HOLD|hold|RELEASE|release)
        # State cannot survive between SSH invocations.
        echo "ERR hold/release unsupported over ssh"
        exit 4
        ;;
    *)
        echo "ERR unknown command"
        exit 2
        ;;
esac
