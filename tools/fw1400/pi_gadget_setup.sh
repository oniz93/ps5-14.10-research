#!/usr/bin/env bash
# Configure a Raspberry Pi Zero (W) as a USB HID keyboard for the console.
#
# Why a Pi Zero instead of a microcontroller: the OTG port can present a standard boot-protocol
# keyboard through the kernel's configfs gadget stack, so there is no firmware to write, no toolchain,
# and no second wire for commands - WiFi carries those. PS5 accepts ordinary USB keyboards (verified),
# so nothing about controller verification applies.
#
# Prerequisites on the Pi (Raspberry Pi OS):
#   1. /boot/firmware/config.txt:      dtoverlay=dwc2
#   2. /boot/firmware/cmdline.txt:     modules-load=dwc2,libcomposite   (same line, after rootwait)
#   3. reboot
#
# Then run this as root. It is idempotent: an existing gadget is torn down and recreated.

set -u

GADGET=/sys/kernel/config/usb_gadget/ps5kbd
# Standard boot keyboard: 8-byte reports, modifiers + 6 key slots. A consumer-control or vendor
# descriptor would not be understood by a console's HID host.
REPORT_DESC='\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x01\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x01\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0'

if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root" >&2
    exit 1
fi

modprobe libcomposite || { echo "libcomposite unavailable - is dtoverlay=dwc2 set?" >&2; exit 1; }
mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config

# Tear down anything left over, so re-running after a failed attempt works.
if [ -d "$GADGET" ]; then
    if [ -e "$GADGET/UDC" ]; then echo "" > "$GADGET/UDC" 2>/dev/null || true; fi
    find "$GADGET/configs" -type l -delete 2>/dev/null || true
    rmdir "$GADGET"/functions/* 2>/dev/null || true
    rmdir "$GADGET"/configs/*/strings/* 2>/dev/null || true
    rmdir "$GADGET"/configs/* 2>/dev/null || true
    rmdir "$GADGET"/strings/* 2>/dev/null || true
    rmdir "$GADGET" 2>/dev/null || true
fi

mkdir -p "$GADGET"
cd "$GADGET" || exit 1
echo 0x1d6b > idVendor
echo 0x0104 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "ps5kbd0001" > strings/0x409/serialnumber
echo "local lab" > strings/0x409/manufacturer
echo "Console Keyboard Bridge" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "HID keyboard" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol     # 1 = keyboard
echo 1 > functions/hid.usb0/subclass     # 1 = boot interface
echo 8 > functions/hid.usb0/report_length
printf "$REPORT_DESC" > functions/hid.usb0/report_desc

ln -s functions/hid.usb0 configs/c.1/ || { echo "link failed" >&2; exit 1; }

UDC_NAME=$(ls /sys/class/udc 2>/dev/null | head -1)
if [ -z "$UDC_NAME" ]; then
    echo "no UDC found - dwc2 is not in peripheral mode (check dtoverlay=dwc2)" >&2
    exit 1
fi
echo "$UDC_NAME" > UDC || { echo "failed to bind $UDC_NAME" >&2; exit 1; }

sleep 1
if [ ! -e /dev/hidg0 ]; then
    echo "gadget bound to $UDC_NAME but /dev/hidg0 is missing" >&2
    exit 1
fi
chmod 666 /dev/hidg0
echo "ready: /dev/hidg0 bound to $UDC_NAME"
echo "verify with: lsusb  (expect 1d6b:0104) and then run pi_kbd_daemon.py"
