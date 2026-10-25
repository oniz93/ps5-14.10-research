"""Stand-in for the Pico firmware, for testing the host client without hardware.

Replies exactly as ps5key.py does, so a wrong command name or a framing bug shows up here instead of
as silence on the console. Accepts connections in a loop because the host client opens a fresh
connection per command.
"""
import socket
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port))
srv.listen(4)
print(f"fake bridge on {port}", flush=True)

while True:
    conn, _peer = srv.accept()
    buf = b""
    with conn:
        while True:
            data = conn.recv(256)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode().strip()
                up = cmd.upper()
                if up == "PING":
                    reply = "PONG"
                elif up == "STATUS":
                    reply = "READY"
                elif up.startswith(("PRESS", "HOLD", "RELEASE", "SEQUENCE", "ALLUP")):
                    reply = "OK"
                else:
                    reply = "ERR unknown command"
                print(f"  rx {cmd!r} -> {reply}", flush=True)
                conn.sendall((reply + "\n").encode())
