#!/usr/bin/env python3
"""A LAN lab for the PS5 Guide WebView: DNS + self-signed HTTPS + beacon log.

Why this exists
---------------
The console's User's Guide app hosts a WebView, and on current firmware it fetches
its shell from `ps5.np.playstation.net` and its content from `manuals.playstation.net`.
Point both at a LAN host and serve a page, and you get arbitrary JavaScript execution
on the console **with no exploit of any kind** — no jailbreak, no save game, no second
console. That is the only attack surface reachable on a stock unit today.

Verified against a retail 14.10 console (see the 14.10 research repo,
`docs/BROWSER_ENTRY_INFRA_2026-10-19.md`). The recipe is reproduced here because every
step of it has a trap:

  * `guides.playstation.com` is stale — hijacking it does nothing
  * a self-signed cert is accepted after an on-screen warning, no pinning observed
  * the shell requests `/document/<lang>/ps5/src/...`, so a server that only serves
    `/src/...` 404s every module and the page renders black
  * the app caches DNS and content hard; only a full app restart / system restart
    reliably re-reads, and PS5 keeps separate DNS per wired/Wi-Fi profile
  * if IPv6 DNS is automatic it can bypass your IPv4 DNS entirely

Usage
-----
    # 1. one-time: cert with the SANs the console needs
    python3 guide_lab.py --mkcert

    # 2. start both servers (root required for :53 and :443)
    sudo python3 guide_lab.py --serve --lan-ip 192.168.1.50

    # 3. on the console: Settings → Network → Set Up Internet Connection →
    #    your profile → Advanced → DNS Settings → Manual → 192.168.1.50
    #    then open the User's Guide and accept the certificate warning

Results land in `guide_lab/results/beacons.jsonl` — one JSON object per beacon, which
is the only crash oracle available without a debugger: a case that beacons `start`
and never `survived`/`threw` took the WebProcess down.
"""

import argparse
import datetime as dt
import json
import os
import socket
import ssl
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(HERE, "guide_lab")
CERT = os.path.join(LAB, "cert.pem")
KEY = os.path.join(LAB, "key.pem")
RESULTS = os.path.join(LAB, "results")
PAYLOAD = os.path.join(LAB, "www")
RESEARCH = os.path.join(HERE, "..", "..", "research", "PS5-14.10-Research")
PROBES = os.path.normpath(os.path.join(RESEARCH, "probes", "phase13_webkit"))
CORPUS = os.path.normpath(os.path.join(RESEARCH, "results", "webkit", "corpus"))

DOMAINS = ["ps5.np.playstation.net", "manuals.playstation.net"]
SAN = ("DNS:ps5.np.playstation.net,DNS:manuals.playstation.net,"
       "DNS:*.np.playstation.net,DNS:*.playstation.net,DNS:*.np.dl.playstation.net")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript",
    ".json": "application/json", ".css": "text/css", ".png": "image/png",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain",
}


def mkcert(force=False):
    os.makedirs(LAB, exist_ok=True)
    if os.path.exists(CERT) and os.path.exists(KEY) and not force:
        print(f"cert already present: {CERT}")
        return
    cmd = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
           "-keyout", KEY, "-out", CERT, "-days", "365",
           "-subj", "/CN=ps5.np.playstation.net",
           "-addext", f"subjectAltName={SAN}"]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"wrote {CERT} and {KEY}\nSANs: {SAN}")


# --------------------------------------------------------------------- DNS

def dns_answer(qname: str, ip: str):
    """Build an A-record answer for qname, or None to leave it unanswered."""
    if qname.lower().rstrip(".") not in DOMAINS:
        return None
    return socket.inet_aton(ip)


def run_dns(lan_ip: str, port: int = 53, verbose: bool = True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
    except OSError as e:
        print(f"DNS: cannot bind 0.0.0.0:{port} ({e}) — is another resolver using it? "
              f"Pick a free port with --dns-port; the console only needs whatever you "
              f"put in its DNS field.")
        return
    if verbose:
        print(f"DNS listening on 0.0.0.0:{port}; {DOMAINS} -> {lan_ip}")
    while True:
        try:
            data, addr = s.recvfrom(512)
        except OSError:
            continue
        if len(data) < 12:
            continue
        tid = data[:2]
        # walk the question name
        i, labels = 12, []
        while i < len(data) and data[i]:
            n = data[i]
            labels.append(data[i + 1:i + 1 + n])
            i += 1 + n
        qname = b".".join(labels).decode("latin-1")
        qtype = struct.unpack(">H", data[i + 1:i + 3])[0] if i + 3 <= len(data) else 0
        question = data[12:i + 5]
        ip = dns_answer(qname, lan_ip) if qtype == 1 else None
        if ip:
            hdr = tid + b"\x81\x80" + struct.pack(">HHHH", 1, 1, 0, 0)
            ans = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + ip
            s.sendto(hdr + question + ans, addr)
            if verbose:
                print(f"  DNS  {qname} -> {lan_ip}")
        elif verbose:
            print(f"  DNS  {qname} (type {qtype}) ignored")


# ------------------------------------------------------------------- HTTPS

class Handler(BaseHTTPRequestHandler):
    server_version = "guide-lab"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):    # noqa: A002 - name matches the base class
        sys.stderr.write("  %s %s\n" % (self.address_string(), format % args))

    def _resolve(self):
        """Map a console request path to a file, stripping the guide prefix."""
        path = urlparse(self.path).path
        # /document/<lang>/ps5/... -> /...
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "document":
            rest = parts[3:]
            path = "/" + "/".join(rest)
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(PAYLOAD, path.lstrip("/")))
        if not full.startswith(PAYLOAD):
            return None
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        return full

    def _serve_file(self):
        full = self._resolve()
        if not full or not os.path.isfile(full):
            body = b"not found\n"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
            return
        ext = os.path.splitext(full)[1].lower()
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _resume_index(self):
        """First case that beaconed start but never survived/threw, else 0."""
        path = os.path.join(RESULTS, "beacons.jsonl")
        if not os.path.exists(path):
            return 0
        started, done = set(), set()
        for line in open(path):
            try:
                body = json.loads(line)["body"]
            except Exception:                       # noqa: BLE001
                continue
            if body.startswith("start:"):
                started.add(int(body.split(":")[1]))
            elif body.startswith(("survived:", "threw:")):
                done.add(int(body.split(":")[1]))
        lost = sorted(started - done)
        return lost[0] if lost else 0

    def _log_beacon(self, tag: str):
        rec = {"t": dt.datetime.now().isoformat(timespec="milliseconds"),
               "client": self.client_address[0], "path": self.path,
               "ua": self.headers.get("User-Agent", ""), "body": tag}
        os.makedirs(RESULTS, exist_ok=True)
        with open(os.path.join(RESULTS, "beacons.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        sys.stderr.write(f"  beacon {rec['client']} {tag[:90]}\n")

    def _send_bytes(self, data: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path

        # The console code beacons as a GET: /beacon/V172-<session>-<tag>?t=..&n=..
        if path.startswith("/beacon/"):
            tag = path[len("/beacon/"):]
            self._log_beacon(tag)
            self._send_bytes(b"", "text/plain", 204)
            return

        # Probe scripts are navigated to as documents, so they must be served as HTML.
        if path.startswith("/probe/"):
            name = os.path.basename(path)
            full = os.path.join(PROBES, name)
            if os.path.isfile(full):
                # A probe is plain JS but the console navigates to it as a document,
                # so it has to be wrapped or the browser renders the source as text.
                src = open(full, "r", encoding="utf-8", errors="replace").read()
                src = src.replace("</script", "<\\/script")
                page = ("<!doctype html><meta charset=\"utf-8\"><title>probe</title>"
                        "<body><script>\n" + src + "\n</script></body>")
                self._send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send_bytes(b"probe not found\n", "text/plain", 404)
            return

        # Corpus pages and the manifest, from the harvested corpus directory.
        if path.startswith("/corpus/"):
            full = os.path.normpath(os.path.join(CORPUS, path[len("/corpus/"):]))
            if CORPUS and full.startswith(CORPUS) and os.path.isfile(full):
                ext = os.path.splitext(full)[1].lower()
                self._send_bytes(open(full, "rb").read(),
                                 CONTENT_TYPES.get(ext, "application/octet-stream"))
            else:
                self._send_bytes(b"corpus miss\n", "text/plain", 404)
            return

        if path == "/resume":
            n = self._resume_index()
            self.send_response(302)
            self.send_header("Location", f"/runner.html?i={n}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._serve_file()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)[:65536] if n else b""
        rec = {
            "t": dt.datetime.now().isoformat(timespec="milliseconds"),
            "client": self.client_address[0],
            "path": urlparse(self.path).path,
            "ua": self.headers.get("User-Agent", ""),
            "body": raw.decode("utf-8", "replace"),
        }
        # beacons arrive as text/plain (sendBeacon) or form-encoded (XHR fallback)
        if rec["body"].startswith("d="):
            rec["body"] = parse_qs(rec["body"])["d"][0]
        os.makedirs(RESULTS, exist_ok=True)
        with open(os.path.join(RESULTS, "beacons.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        sys.stderr.write(f"  beacon {rec['client']} {rec['body'][:80]}\n")
        if urlparse(self.path).path == "/beacon":
            self.send_response(204)
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


def run_https(port: int, verbose=True):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"HTTPS listening on 0.0.0.0:{port}, serving {PAYLOAD}")
    httpd.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mkcert", action="store_true")
    ap.add_argument("--force", action="store_true", help="regenerate the cert")
    ap.add_argument("--serve", action="store_true", help="run DNS + HTTPS")
    ap.add_argument("--lan-ip", help="this host's LAN address that the console should resolve to")
    ap.add_argument("--https-port", type=int, default=443)
    ap.add_argument("--dns-port", type=int, default=53)
    ap.add_argument("--https-only", action="store_true")
    ap.add_argument("--report", action="store_true", help="summarise the beacon log")
    a = ap.parse_args()

    if a.mkcert:
        mkcert(a.force)
        return

    if a.report:
        path = os.path.join(RESULTS, "beacons.jsonl")
        if not os.path.exists(path):
            raise SystemExit("no beacons yet")
        rows = [json.loads(l) for l in open(path) if l.strip()]
        started, done, uas = set(), set(), []
        for r in rows:
            b, ua = r["body"], r.get("ua", "")
            if ua and ua not in uas:
                uas.append(ua)
            if b.startswith("start:"):
                started.add(b.split(":", 1)[1])
            elif b.startswith(("survived:", "threw:")):
                done.add(b.split(":", 1)[1])
            elif "V172-" in b:                       # /beacon/V172-<session>-<tag>
                tag = b.split("V172-", 1)[1].split("-", 1)[-1]
                if tag.startswith("BEFORE-"):
                    started.add(tag[len("BEFORE-"):])
                elif tag.startswith(("OK-", "GAP-")):
                    done.add(tag.split("-", 1)[1])
        lost = sorted(started - done)
        print(json.dumps({"beacons": len(rows), "cases_started": len(started),
                          "cases_finished": len(done),
                          "started_but_never_finished": lost,
                          "user_agents": uas[:4]},
                         indent=2))
        return

    if a.serve:
        if not a.lan_ip:
            raise SystemExit("--lan-ip is required with --serve")
        if not (os.path.exists(CERT) and os.path.exists(KEY)):
            mkcert()
        threads = [threading.Thread(target=run_https, args=(a.https_port,), daemon=True)]
        if not a.https_only:
            threads.append(threading.Thread(target=run_dns, args=(a.lan_ip, a.dns_port),
                                            daemon=True))
        for t in threads:
            t.start()
        print(f"\nConsole setup: DNS -> {a.lan_ip}; then open the User's Guide.")
        print(f"Beacons -> {os.path.join(RESULTS, 'beacons.jsonl')}\n")
        try:
            while True:
                for t in threads:
                    t.join(1)
        except KeyboardInterrupt:
            print("\nstopped")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
