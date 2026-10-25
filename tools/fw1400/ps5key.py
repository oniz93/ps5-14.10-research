"""PS5 keyboard bridge - MicroPython firmware for RP2040 (Pico W or any RP2040 board).

Presents as a standard USB HID keyboard and accepts commands over WiFi (TCP) or UART.

Why a keyboard rather than a controller: PS5 verifies controllers (L2CAP PSMs 0x11/0x13, feature-set
handshake, CRC32), so emulating a DualSense is a reverse-engineering project. It accepts ordinary USB
keyboards with no such checks, and on the Guide those keys are full control: arrows move, Enter is OK,
Esc backs out, F3 is the Options button (closes the Guide). Verified on hardware.

Command protocol, one per line:
    PING                  -> PONG
    PRESS <key> [ms]      -> OK        momentary, default 120 ms
    HOLD <key>            -> OK
    RELEASE <key>         -> OK
    ALLUP                 -> OK        release everything (panic button)
    SEQUENCE <k1,k2,..> [gap] -> OK

Safety: a deadman timer releases every key if no command arrives for DEADMAN_S seconds. A stuck
modifier on a console that cannot be rebooted cheaply is not an acceptable failure mode, and this
also covers the bridge process dying mid-press.

Deploy: copy to the board as main.py. On Pico W set WIFI_SSID/WIFI_PASSWORD; on a plain RP2040 the
WiFi block is skipped and UART is used.
"""

import sys
import time

try:
    import usb_hid
except ImportError:
    usb_hid = None

# ----------------------------------------------------------------------------- configuration

DEADMAN_S = 15
DEFAULT_PRESS_MS = 120
TCP_PORT = 8000
UART_TX_PIN = 0      # plain-RP2040 builds: change to whichever free GPIO the board exposes
UART_RX_PIN = 1
UART_BAUD = 115200

WIFI_SSID = ""       # set for Pico W; left empty on boards without WiFi
WIFI_PASSWORD = ""

# USB HID keyboard usage IDs
KEYS = {
    "enter": 0x28, "escape": 0x29, "esc": 0x29, "tab": 0x2B, "space": 0x2C,
    "backspace": 0x2A, "delete": 0x4C,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D,
    "home": 0x4A, "end": 0x4D,
}

_held = set()


# ----------------------------------------------------------------------------- HID output

class Keyboard:
    """Thin wrapper so the rest of the file does not care how the board is built."""

    def __init__(self):
        self.dev = None
        if usb_hid is None:
            return
        for d in usb_hid.devices:
            # The built-in KEYBOARD descriptor: boot-protocol compatible, which is what a console's
            # HID host expects.
            if getattr(d, "usage_page", None) == 0x01 and getattr(d, "usage", None) == 0x06:
                self.dev = d
                break

    def _send(self, keycodes):
        if self.dev is None:
            return
        report = bytearray(8)
        codes = [KEYS[k] for k in keycodes if k in KEYS][:6]
        for i, c in enumerate(codes):
            report[2 + i] = c
        self.dev.send_report(report)

    def press(self, key):
        _held.add(key)
        self._send(sorted(_held))

    def release(self, key):
        _held.discard(key)
        self._send(sorted(_held))

    def release_all(self):
        _held.clear()
        self._send([])


# ----------------------------------------------------------------------------- transports

def handle(line, kbd):
    parts = line.strip().split()
    if not parts:
        return None
    cmd = parts[0].upper()

    if cmd == "PING":
        return "PONG"
    if cmd == "ALLUP":
        kbd.release_all()
        return "OK"
    if cmd == "STATUS":
        return "READY"
    if cmd in ("PRESS", "HOLD", "RELEASE"):
        if len(parts) < 2:
            return "ERR missing key"
        key = parts[1].lower()
        if key not in KEYS:
            return "ERR unknown key"
        if cmd == "HOLD":
            kbd.press(key)
            return "OK"
        if cmd == "RELEASE":
            kbd.release(key)
            return "OK"
        ms = int(parts[2]) if len(parts) > 2 else DEFAULT_PRESS_MS
        kbd.press(key)
        time.sleep(ms / 1000.0)
        kbd.release(key)
        return "OK"
    if cmd == "SEQUENCE":
        if len(parts) < 2:
            return "ERR missing keys"
        names = [n for n in parts[1].split(",") if n]
        gap = int(parts[2]) if len(parts) > 2 else 150
        for n in names:
            if n.lower() not in KEYS:
                return "ERR unknown key %s" % n
            kbd.press(n.lower())
            time.sleep(DEFAULT_PRESS_MS / 1000.0)
            kbd.release(n.lower())
            time.sleep(gap / 1000.0)
        return "OK"
    return "ERR unknown command"


def serve_stream(readline, write, kbd, name):
    """Shared loop for TCP and UART: a transport only has to give us readline() and write()."""
    print("bridge up on", name)
    last_rx = time.time()
    while True:
        line = readline()
        if line is None:
            if time.time() - last_rx > DEADMAN_S:
                kbd.release_all()
            continue
        last_rx = time.time()
        reply = handle(line, kbd)
        if reply:
            write(reply + "\n")


# ----------------------------------------------------------------------------- main

def main():
    kbd = Keyboard()

    if WIFI_SSID:
        import network
        import socket

        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            for _ in range(40):
                if wlan.isconnected():
                    break
                time.sleep(0.25)
        if not wlan.isconnected():
            print("wifi failed; falling back to UART")
        else:
            addr = wlan.ifconfig()[0]
            print("bridge listening on %s:%d" % (addr, TCP_PORT))
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", TCP_PORT))
            srv.listen(1)
            while True:
                conn, peer = srv.accept()
                conn.settimeout(1.0)
                buf = b""

                def readline():
                    nonlocal buf
                    try:
                        chunk = conn.recv(256)
                    except OSError:
                        # Timeout: report "no data" so the deadman timer can run. Only close on a
                        # genuinely dead socket.
                        try:
                            conn.send(b"")
                            return None
                        except OSError:
                            raise
                    if not chunk:
                        return None
                    buf += chunk
                    if b"\n" not in buf:
                        return None
                    line, buf = buf.split(b"\n", 1)
                    return line.decode("utf-8", "replace")

                try:
                    serve_stream(readline, lambda s: conn.send(s.encode()), kbd, str(peer))
                except OSError:
                    print("client gone")
                    kbd.release_all()

    # UART fallback (also the path used on a plain RP2040 with no WiFi)
    from machine import UART, Pin
    uart = UART(0, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
    buf = b""

    def uart_readline():
        nonlocal buf
        data = uart.read(64)
        if not data:
            return None
        buf += data
        if b"\n" not in buf:
            return None
        line, buf = buf.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    serve_stream(uart_readline, lambda s: uart.write(s.encode()), kbd, "uart")


main()
