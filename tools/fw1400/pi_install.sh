#!/bin/bash
# Make the keyboard gadget permanent on the Pi, so a reboot cannot leave the console without a keyboard.
#
# Run as root after the files are on the box. Idempotent: re-running reinstalls and restarts the unit.
#
#   pi_install.sh            # install + enable + start
#   pi_install.sh --status   # report only

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST=/usr/local/sbin/pi_gadget_setup.sh
UNIT=/etc/systemd/system/ps5kbd-gadget.service

if [ "${1:-}" = "--status" ]; then
    echo "unit:    $(systemctl is-enabled ps5kbd-gadget 2>/dev/null || echo 'not installed') / $(systemctl is-active ps5kbd-gadget 2>/dev/null || echo 'inactive')"
    echo "hidg0:   $([ -e /dev/hidg0 ] && echo present || echo MISSING)"
    echo "udc:     $(cat /sys/class/udc/*/state 2>/dev/null | head -1 || echo none)"
    echo "ssh:     $(systemctl is-active ssh 2>/dev/null || echo inactive)"
    exit 0
fi

install -m 0755 "$HERE/pi_gadget_setup.sh" "$DEST"
install -m 0644 "$HERE/ps5kbd-gadget.service" "$UNIT"

systemctl daemon-reload
systemctl enable ps5kbd-gadget >/dev/null
# --no-block keeps this from hanging if the console is not plugged in yet.
systemctl restart ps5kbd-gadget

sleep 1
echo "installed. status:"
"$HERE/pi_install.sh" --status
