#!/usr/bin/env python3
"""Send controller input to the console through the MITM bridge.

Design note: this never synthesises a DualSense. A genuine controller sits behind the Pico, answers
PS5's verification handshake, and the bridge only ORs button bits into the reports it forwards. That
keeps the controller fully usable as a controller and means we never have to reimplement Sony's
L2CAP PSMs 0x11/0x13 protocol or the feature-set handshake.

Wire protocol (line-oriented ASCII, so a human can drive it with a serial terminal):
    PING                 -> PONG
    STATUS               -> STATE passthrough|inject|error
    PRESS <btn> [ms]     -> OK            momentary press, default 120 ms
    HOLD <btn>           -> OK
    RELEASE <btn>        -> OK
    SEQUENCE <b1,b2,..> [gap]  -> OK      one press per button, gap ms apart
    Buttons: cross circle square triangle up down left right l1 r1 l2 r2 l3 r3
             options create ps touchpad

The Mac side is deliberately tolerant: it reconnects if the port disappears (a Pico reset drops the
port), and every command has a timeout so a wedged bridge cannot hang a test loop.
"""

import argparse
import os
import select
import sys
import termios
import time
import tty

BUTTONS = {
    "cross", "circle", "square", "triangle",
    "up", "down", "left", "right",
    "l1", "r1", "l2", "r2", "l3", "r3",
    "options", "create", "ps", "touchpad",
}


class Bridge:
    def __init__(self, port: str, baud: int = 115200, timeout: float = 2.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.fd = None

    def open(self) -> None:
        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        # Raw 8N1, no echo, no canonical mode: the bridge speaks fixed lines.
        tty.setraw(self.fd)
        attrs = termios.tcgetattr(self.fd)
        attrs[4] = attrs[5] = termios.B115200 if self.baud == 115200 else termios.B9600
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def command(self, line: str) -> str:
        if self.fd is None:
            raise RuntimeError("bridge not open")
        os.write(self.fd, (line.strip() + "\n").encode())
        deadline = time.time() + self.timeout
        buf = b""
        while time.time() < deadline:
            r, _, _ = select.select([self.fd], [], [], max(0.0, deadline - time.time()))
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 256)
            except BlockingIOError:
                continue
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                return buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        raise TimeoutError(f"no reply to {line!r} within {self.timeout}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="serial device, e.g. /dev/tty.usbserial-XXXX")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true", help="print commands instead of sending")
    ap.add_argument("--selftest", action="store_true",
                    help="verify framing against a pseudo-terminal loopback")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("ping")
    sub.add_parser("status")
    p = sub.add_parser("press"); p.add_argument("button"); p.add_argument("ms", nargs="?", type=int, default=120)
    p = sub.add_parser("hold"); p.add_argument("button")
    p = sub.add_parser("release"); p.add_argument("button")
    p = sub.add_parser("sequence"); p.add_argument("buttons"); p.add_argument("gap", nargs="?", type=int, default=150)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not args.cmd:
        ap.print_help()
        return 2

    if args.cmd in ("press", "hold", "release") and args.button not in BUTTONS:
        sys.stderr.write(f"unknown button {args.button!r}; known: {', '.join(sorted(BUTTONS))}\n")
        return 2

    if args.cmd == "ping":
        line = "PING"
    elif args.cmd == "status":
        line = "STATUS"
    elif args.cmd == "press":
        line = f"PRESS {args.button} {args.ms}"
    elif args.cmd == "hold":
        line = f"HOLD {args.button}"
    elif args.cmd == "release":
        line = f"RELEASE {args.button}"
    else:
        line = f"SEQUENCE {args.buttons} {args.gap}"

    if args.dry_run or not args.port:
        print(line)
        return 0

    bridge = Bridge(args.port, args.baud, args.timeout)
    bridge.open()
    try:
        print(bridge.command(line))
    except TimeoutError as e:
        sys.stderr.write(f"{e}\n")
        return 3
    finally:
        bridge.close()
    return 0


def selftest() -> int:
    """Prove the framing against a pty that echoes a canned reply.

    This exists because the real bridge is hardware; without it, every bug in this file would only
    surface as 'nothing happened on the console', which is indistinguishable from a dead bridge.
    """
    import pty
    master, slave = pty.openpty()
    slave_name = os.ttyname(slave)
    replies = {"PING": "PONG", "STATUS": "STATE passthrough"}

    pid = os.fork()
    if pid == 0:
        # The child must hold the MASTER end: bytes written by the parent to the slave appear on the
        # master, so reading the slave here would block forever and the test would always time out.
        os.close(slave)
        while True:
            try:
                data = os.read(master, 256)
            except OSError:
                time.sleep(0.02)   # EIO while no slave is open; keep waiting rather than dying
                continue
            if not data:
                break
            line = data.decode("utf-8", "replace").strip()
            if not line:
                continue
            reply = replies.get(line)
            if reply is None and line.startswith("PRESS "):
                reply = "OK"
            if reply is None:
                reply = "ERR unknown"
            os.write(master, (reply + "\n").encode())
        os._exit(0)

    # Open the bridge BEFORE dropping the parent's slave fd: with no slave open at all the pty
    # master returns EIO, which killed the child mid-test.
    b = Bridge(slave_name, timeout=2.0)
    b.open()
    os.close(slave)
    ok = True
    for cmd, want in (("PING", "PONG"), ("STATUS", "STATE passthrough"), ("PRESS cross 120", "OK")):
        got = b.command(cmd)
        status = "ok" if got == want else "MISMATCH"
        if got != want:
            ok = False
        print(f"{cmd:20s} -> {got!r:22s} [{status}]")
    b.close()
    os.kill(pid, 15)
    os.waitpid(pid, 0)
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
