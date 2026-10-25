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

# Build an 8-byte report: modifiers, reserved, then up to six keycodes.
send_report() {
    local out='\x00\x00' i c
    for i in 1 2 3 4 5 6; do
        c="$(code_for "${!i}")"
        if [ -n "$c" ]; then out="$out$c"; else out="$out"'\x00'; fi
    done
    if ! printf "$out" > "$DEV" 2>/dev/null; then
        echo "ERR no host attached"
        return 1
    fi
    return 0
}

all_up() { printf '\x00\x00\x00\x00\x00\x00\x00\x00' > "$DEV" 2>/dev/null || true; }

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
    PRESET|PRESS|press)
        key="$1"; ms="${2:-120}"
        c="$(code_for "$key")"
        [ -z "$c" ] && { echo "ERR unknown key"; exit 2; }
        send_report "$c" || exit 3
        sleep "$(awk -v m="$ms" 'BEGIN{printf "%.3f", m/1000}')"
        all_up
        echo OK
        ;;
    SEQUENCE|sequence)
        keys="$1"; gap="${2:-150}"
        IFS=',' read -ra list <<< "$keys"
        for k in "${list[@]}"; do
            c="$(code_for "$k")"
            [ -z "$c" ] && { echo "ERR unknown key $k"; exit 2; }
            send_report "$c" || exit 3
            sleep 0.12
            all_up
            sleep "$(awk -v m="$gap" 'BEGIN{printf "%.3f", m/1000}')"
        done
        echo OK
        ;;
    ALLUP|allup)
        all_up
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
