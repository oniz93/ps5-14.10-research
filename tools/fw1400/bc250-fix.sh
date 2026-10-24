#!/usr/bin/env bash
# One-shot BC-250 fix: stop the board sleeping, and move VRAM back to RAM.
#
# Run with sudo:  sudo bash ~/bc250-fix.sh [vram_mb] [--reboot]
# Default vram_mb is 512, the community-recommended minimum, which returns ~15 GB to the CPU.
#
# Two independent problems, two independent fixes:
#
# 1. SUSPEND. Bazzite ships a Steam-Deck power profile (/etc/systemd/logind.conf.d/deck.conf)
#    and runs KDE Plasma, so powerdevil suspends the box after a few idle minutes. Masking the
#    sleep targets is the layer that matters, because it makes the request fail no matter which
#    component makes it - powerdevil, logind's IdleAction, or a keypress.
#
# 2. KILLUSERPROCESSES. deck.conf also sets KillUserProcesses=true, which is why a WebKit build
#    died when an SSH session dropped: logind kills every process in the user's session on
#    logout. Setting it to no is what makes an unattended build actually unattended.
#
# 3. VRAM. The stock P3.00 BIOS splits the shared 16 GB as 8 GB RAM / 8 GB VRAM, which is why
#    this board reports 7.6 GB usable. fanoush/bc250_memcfg writes the split into extended CMOS,
#    so no BIOS flash is needed. The change is stored in battery-backed RTC RAM: it survives a
#    BIOS reflash and normal power-off, and is lost only on a CMOS clear or battery pull.

set -eu

VRAM_MB=${1:-512}
REBOOT=${2:-}

if [ "$(id -u)" -ne 0 ]; then
    echo "run me with sudo: sudo bash $0 [vram_mb] [--reboot]" >&2
    exit 1
fi

echo "=== before ==="
printf 'vram carve: '; cat /sys/class/drm/card*/device/mem_info_vram_total 2>/dev/null | head -1
free -m | awk '/Mem:/{printf "ram total: %s MB, available: %s MB\n", $2, $7}'
printf 'killuserprocesses: '; loginctl show-session "$(loginctl list-sessions --no-legend | awk "NR==1{print \$1}")" -p KillUserProcesses 2>/dev/null || echo "(per-user)"
systemctl is-enabled sleep.target suspend.target hibernate.target 2>&1 | tr '\n' ' '; echo

echo
echo "=== 1. logind: no idle action, no key handling, keep user processes ==="
install -d /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/99-bc250-nosleep.conf <<'EOF'
# Added for this board: the machine is used as a headless build host, and a Steam-Deck-style
# profile was suspending it after a few idle minutes and killing user processes on logout.
[Login]
IdleAction=ignore
IdleActionSec=0
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandlePowerKey=ignore
KillUserProcesses=no
EOF
echo "wrote /etc/systemd/logind.conf.d/99-bc250-nosleep.conf"

echo
echo "=== 2. mask sleep targets so any suspend request fails ==="
systemctl mask --quiet sleep.target suspend.target hibernate.target hybrid-sleep.target \
    systemd-suspend.service systemd-hibernate.service systemd-hybrid-sleep.service \
    systemd-suspend-then-hibernate.service 2>/dev/null || true
systemctl daemon-reload
systemctl restart systemd-logind
echo "masked: $(systemctl is-enabled sleep.target suspend.target hibernate.target 2>&1 | tr '\n' ' ')"

echo
echo "=== 3. VRAM split -> ${VRAM_MB} MB (from extended CMOS, no BIOS flash) ==="
MEMCFG="$HOME/bc250_memcfg/bc250memcfg"
if [ -x "$MEMCFG" ]; then
    "$MEMCFG" UMA_SIZE "$VRAM_MB" || echo "memcfg failed - nothing changed"
    echo "--- current CMOS values ---"
    "$MEMCFG" 2>/dev/null | head -12
else
    echo "not built at $MEMCFG - build it first: cd ~/bc250_memcfg && make" >&2
fi

echo
echo "=== after (RAM figure updates only after reboot) ==="
printf 'vram carve: '; cat /sys/class/drm/card*/device/mem_info_vram_total 2>/dev/null | head -1
free -m | awk '/Mem:/{printf "ram total: %s MB\n", $2}'
echo
echo "suspend test (should fail):"
systemctl suspend 2>&1 | head -2 || true

echo
if [ "$REBOOT" = "--reboot" ]; then
    echo "rebooting to apply the VRAM split..."
    systemctl reboot
else
    echo "Now reboot to apply the VRAM split:  sudo systemctl reboot"
fi
