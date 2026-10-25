"""Poke a serial port to find out whether a MicroPython REPL is on the other end.

Needed because a Pico in BOOTSEL mode shows up as a mass-storage volume and *no* serial port, while a
flashed one shows a tty but no volume - and this Mac has two unrelated usbmodem devices, so guessing
from the device name is not good enough.
"""
import os
import select
import sys
import termios
import time

port = sys.argv[1]
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
attrs = termios.tcgetattr(fd)
attrs[0] = 0
attrs[1] = 0
attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
attrs[3] = 0
attrs[4] = attrs[5] = termios.B115200 if baud == 115200 else termios.B9600
attrs[6][termios.VMIN] = 0
attrs[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, attrs)

# Ctrl-C twice interrupts any running program, then a newline gets a fresh prompt.
os.write(fd, b"\r\x03\x03\r")

buf = b""
end = time.time() + 3.0
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.2)
    if not r:
        continue
    try:
        chunk = os.read(fd, 512)
    except BlockingIOError:
        continue
    if not chunk:
        continue
    buf += chunk

os.close(fd)
text = buf.decode("utf-8", "replace")
print(f"--- {port} ---")
print(repr(text[:400]))
if "MicroPython" in text:
    print("VERDICT: MicroPython REPL")
elif ">>>" in text:
    print("VERDICT: prompt seen (likely MicroPython)")
else:
    print("VERDICT: no REPL response")
