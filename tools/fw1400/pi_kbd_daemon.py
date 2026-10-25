#!/usr/bin/env python3
"""TCP -> /dev/hidg0 keyboard daemon. Runs on the Pi Zero alongside the gadget.

Accepts the same line protocol as the MicroPython firmware, so the Mac-side client does not care
which board is on the other end:

    PING | STATUS | PRESS <key> [ms] | HOLD <key> | RELEASE <key> | SEQUENCE <k1,k2,..> [gap] | ALLUP

Why a daemon rather than writing reports directly from the watcher: the console enumerates the gadget
only while the Pi is running it, and this keeps the HID writes on the same machine as the gadget, so a
network hiccup cannot leave a key held down.

Safety: a watchdog releases every key if no command arrives for DEADMAN_S seconds.

    python3 pi_kbd_daemon.py --device /dev/hidg0 --port 8000
"""

import argparse
import os
import socket
import sys
import threading
import time

KEYS = {
    "enter": 0x28, "escape": 0x29, "esc": 0x29, "tab": 0x2B, "space": 0x2C,
    "backspace": 0x2A, "delete": 0x4C,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D,
    "home": 0x4A, "end": 0x4D,
}

DEFAULT_PRESS_MS = 120
DEADMAN_S = 15


class HidKeyboard:
    def __init__(self, device: str):
        self.device = device
        self.fd = None
        self.held = set()
        self.lock = threading.Lock()

    def open(self) -> None:
        # O_APPEND so the same code path works against a regular file in testing; char devices
        # ignore it.
        self.fd = os.open(self.device, os.O_WRONLY | os.O_APPEND)

    def _write(self, keycodes) -> None:
        if self.fd is None:
            return
        report = bytearray(8)
        for i, k in enumerate([KEYS[c] for c in keycodes if c in KEYS][:6]):
            report[2 + i] = k
        os.write(self.fd, bytes(report))

    def press(self, key: str) -> None:
        with self.lock:
            self.held.add(key)
            self._write(sorted(self.held))

    def release(self, key: str) -> None:
        with self.lock:
            self.held.discard(key)
            self._write(sorted(self.held))

    def release_all(self) -> None:
        with self.lock:
            self.held.clear()
            self._write([])


class Server:
    def __init__(self, kbd: HidKeyboard, port: int, bind: str):
        self.kbd = kbd
        self.port = port
        self.bind = bind
        self.last_rx = time.time()
        self.watchdog = threading.Thread(target=self._deadman, daemon=True)

    def _deadman(self) -> None:
        while True:
            time.sleep(1)
            if self.kbd.held and time.time() - self.last_rx > DEADMAN_S:
                sys.stderr.write(f"deadman: releasing {sorted(self.kbd.held)} after {DEADMAN_S}s idle\n")
                self.kbd.release_all()

    def handle(self, line: str) -> str:
        parts = line.split()
        if not parts:
            return ""
        cmd = parts[0].upper()

        if cmd == "PING":
            return "PONG"
        if cmd == "STATUS":
            return "READY"
        if cmd == "ALLUP":
            self.kbd.release_all()
            return "OK"
        if cmd in ("PRESS", "HOLD", "RELEASE"):
            if len(parts) < 2:
                return "ERR missing key"
            key = parts[1].lower()
            if key not in KEYS:
                return "ERR unknown key"
            if cmd == "HOLD":
                self.kbd.press(key)
                return "OK"
            if cmd == "RELEASE":
                self.kbd.release(key)
                return "OK"
            ms = int(parts[2]) if len(parts) > 2 else DEFAULT_PRESS_MS
            self.kbd.press(key)
            time.sleep(ms / 1000.0)
            self.kbd.release(key)
            return "OK"
        if cmd == "SEQUENCE":
            if len(parts) < 2:
                return "ERR missing keys"
            names = [n for n in parts[1].split(",") if n]
            gap = int(parts[2]) if len(parts) > 2 else 150
            for n in names:
                if n.lower() not in KEYS:
                    return "ERR unknown key " + n
                self.kbd.press(n.lower())
                time.sleep(DEFAULT_PRESS_MS / 1000.0)
                self.kbd.release(n.lower())
                time.sleep(gap / 1000.0)
            return "OK"
        return "ERR unknown command"

    def serve(self) -> None:
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.bind, self.port))
        srv.listen(4)
        print(f"listening on {self.bind}:{self.port} -> {self.kbd.device}", flush=True)
        self.watchdog.start()
        while True:
            conn, peer = srv.accept()
            conn.settimeout(1.0)
            buf = b""
            with conn:
                while True:
                    try:
                        data = conn.recv(256)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    self.last_rx = time.time()
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        reply = self.handle(line.decode("utf-8", "replace").strip())
                        if reply:
                            conn.sendall((reply + "\n").encode())
            # A dropped client must not leave a key held down.
            self.kbd.release_all()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/hidg0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--selftest", action="store_true",
                    help="run the protocol against a temp file instead of the gadget")
    args = ap.parse_args()

    if args.selftest:
        import tempfile
        path = tempfile.mktemp(prefix="hidg0-")
        open(path, "wb").close()
        kbd = HidKeyboard(path)
        kbd.open()
        srv = Server(kbd, 0, "127.0.0.1")
        ok = True
        for cmd, want in (("PING", "PONG"), ("STATUS", "READY"), ("PRESS enter 10", "OK"),
                          ("HOLD left", "OK"), ("RELEASE left", "OK"), ("ALLUP", "OK"),
                          ("PRESS bogus", "ERR unknown key")):
            got = srv.handle(cmd)
            if got != want:
                ok = False
            print(f"{cmd:22s} -> {got!r}")
        data = open(path, "rb").read()
        print(f"reports written: {len(data)} bytes ({len(data)//8} reports)")
        os.unlink(path)
        print("selftest:", "PASS" if ok and len(data) >= 8 else "FAIL")
        return 0 if ok else 1

    kbd = HidKeyboard(args.device)
    if not os.path.exists(args.device):
        sys.stderr.write(f"{args.device} not found - run pi_gadget_setup.sh first\n")
        return 2
    kbd.open()
    try:
        Server(kbd, args.port, args.bind).serve()
    finally:
        kbd.release_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
