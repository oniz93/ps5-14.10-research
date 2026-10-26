#!/bin/sh
# One-shot repair, run at boot via systemd.run= on the kernel command line.
#
# Repairs an interrupted dpkg/apt run: the power cycle landed while `apt-get -y dist-upgrade` was
# unpacking packages, which leaves packages in "unpacked but not configured" state and services
# (including ssh) unable to start. The network comes up fine, which is why the board pings but
# refuses port 22.
#
# Writes its log and diagnostics to the boot partition, which is readable from macOS afterwards.

LOG=/boot/firmware/firstrun.log
exec >"$LOG" 2>&1
set -x

echo "=== repair started $(date -u) ==="
export DEBIAN_FRONTEND=noninteractive

# Wait for the network: apt needs it, and systemd.run fires early in boot.
i=0
while [ $i -lt 60 ]; do
    if getent hosts deb.debian.org >/dev/null 2>&1; then
        echo "network up after ${i}s"
        break
    fi
    i=$((i + 3))
    sleep 3
done

# The actual repair. --configure -a fixes unpacked-but-unconfigured packages offline; -f install
# then resolves anything left half-installed.
dpkg --configure -a
# --force-confold: non-interactive, keep existing configs. Without it a conffile prompt blocks the
# repair forever on a box with no console attached.
apt-get -f install -y -o Dpkg::Options::=--force-confold
apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confold openssh-server

systemctl unmask ssh 2>/dev/null || true
systemctl enable ssh
systemctl start ssh || true

# Gadget: install and enable so the console sees a keyboard after every boot from now on.
if [ -f /boot/firmware/pi_gadget_setup.sh ]; then
    install -m 0755 /boot/firmware/pi_gadget_setup.sh /usr/local/sbin/pi_gadget_setup.sh
fi
if [ -f /boot/firmware/ps5kbd-gadget.service ]; then
    install -m 0644 /boot/firmware/ps5kbd-gadget.service /etc/systemd/system/ps5kbd-gadget.service
    systemctl daemon-reload
    systemctl enable ps5kbd-gadget || true
    systemctl start ps5kbd-gadget || true
fi

# Diagnostics for the case where ssh still does not come back.
{
    echo "=== date ==="; date -u
    echo "=== disk ==="; df -h /
    echo "=== ssh unit ==="; systemctl is-enabled ssh; systemctl is-active ssh
    echo "=== sshd config test ==="; /usr/sbin/sshd -t 2>&1 || true
    echo "=== package state ==="; dpkg -l openssh-server 2>&1 | tail -3
    echo "=== failed units ==="; systemctl --failed --no-pager 2>&1 | head -20
    echo "=== hidg ==="; ls -l /dev/hidg0 2>&1
    echo "=== udc ==="; cat /sys/class/udc/*/state 2>&1
} > /boot/firmware/diag.txt 2>&1

# Remove our own hook: systemd.run does not clear itself, so leaving it would re-run this repair -
# and reboot - on every single boot.
if grep -q "systemd.run=" /boot/firmware/cmdline.txt 2>/dev/null; then
    sed -i 's| *systemd\.run=[^ ]*||g; s| *systemd\.run_success_action=[^ ]*||g; s| *systemd\.unit=kernel-command-line\.target||g' /boot/firmware/cmdline.txt
    echo "hook removed; cmdline now:"
    cat /boot/firmware/cmdline.txt
fi

sync
echo "=== repair finished $(date -u) ==="
