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
# repo-local probes win over the third-party clone, so our own PoCs stay tracked
LOCAL_PROBES = os.path.join(HERE, "probes")
CORPUS = os.path.normpath(os.path.join(RESEARCH, "results", "webkit", "corpus"))

DOMAINS = ["ps5.np.playstation.net", "manuals.playstation.net"]
SAN = ("DNS:ps5.np.playstation.net,DNS:manuals.playstation.net,"
       "DNS:guides.playstation.com,DNS:*.playstation.com,"
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
    ca_key = os.path.join(LAB, "ca.key")
    ca_crt = os.path.join(LAB, "ca.pem")
    csr = os.path.join(LAB, "leaf.csr")

    # A bare self-signed leaf gets rejected outright by stricter TLS stacks with
    # "certificate unknown". A private CA signing a proper leaf at least produces a
    # normal chain, which known clients turn into an interstitial instead of a hard
    # failure. It is still untrusted; it just fails the way browsers expect.
    def run(*args):
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", ca_key, "-out", ca_crt, "-days", "3650",
        "-subj", "/CN=PS5 Lab CA", "-addext", "basicConstraints=critical,CA:TRUE")

    run("openssl", "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", KEY, "-out", csr, "-subj", "/CN=ps5.np.playstation.net")

    ext = os.path.join(LAB, "leaf.ext")
    with open(ext, "w") as f:
        f.write(f"subjectAltName={SAN}\nbasicConstraints=CA:FALSE\n"
                "keyUsage=digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n")

    run("openssl", "x509", "-req", "-in", csr, "-CA", ca_crt, "-CAkey", ca_key,
        "-CAcreateserial", "-out", os.path.join(LAB, "leaf.pem"),
        "-days", "825", "-extfile", ext)

    # serve leaf + CA so the client receives a chain
    with open(CERT, "w") as out:
        out.write(open(os.path.join(LAB, "leaf.pem")).read())
        out.write(open(ca_crt).read())
    print(f"wrote CA-signed chain: {CERT} (leaf + CA), key {KEY}\nSANs: {SAN}")


# --------------------------------------------------------------------- DNS

def dns_answer(qname: str, ip: str):
    """Build an A-record answer for qname, or None to leave it unanswered."""
    if qname.lower().rstrip(".") not in DOMAINS:
        return None
    return socket.inet_aton(ip)


def _log_dns(client: str, qname: str, qtype: int, answered: bool):
    os.makedirs(RESULTS, exist_ok=True)
    rec = {"t": dt.datetime.now().isoformat(timespec="milliseconds"),
           "client": client, "qname": qname, "qtype": qtype, "answered": answered}
    with open(os.path.join(RESULTS, "dns.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")


def _forward(data: bytes, upstream: str, timeout: float = 3.0):
    """Relay a query to upstream and return its raw reply, or None."""
    try:
        up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        up.settimeout(timeout)
        up.sendto(data, (upstream, 53))
        reply, _ = up.recvfrom(2048)
        up.close()
        return reply
    except OSError:
        return None


def run_dns(lan_ip: str, port: int = 53, verbose: bool = True, catchall: bool = False,
            upstream: str = "<resolver-ip>"):
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
        if catchall and qtype == 1:
            ip = socket.inet_aton(lan_ip)

        if not ip:
            # Everything that is not one of the hijacked hosts must still resolve
            # normally, or the guide app cannot fetch its own config and renders blank.
            reply = _forward(data, upstream)
            if reply:
                s.sendto(reply, addr)
                _log_dns(addr[0], qname, qtype, True)
                if verbose:
                    print(f"  DNS  {qname} (type {qtype}) -> upstream")
            else:
                _log_dns(addr[0], qname, qtype, False)
                if verbose:
                    print(f"  DNS  {qname} (type {qtype}) upstream FAILED")
            continue

        _log_dns(addr[0], qname, qtype, True)
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
    def end_headers(self):
        """Every response carries cross-origin isolation headers.

        Without COOP+COEP the page is not crossOriginIsolated and SharedArrayBuffer
        stays undefined, no matter what the engine supports. The resizable-ArrayBuffer
        serialization bug fixed upstream in Oct 2024 needs a second thread to mutate the
        buffer mid-serialization, so without SAB it is unreachable and the whole lead
        dies. CORP is cross-origin so subresources still load.
        """
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        super().end_headers()

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

    def _current_probe(self):
        """If www/current names a probe, the root serves that probe instead.

        Lets a run be switched without restarting the server, which matters because
        every restart means killing a sudo process and re-accepting the console's
        certificate warning.
        """
        f = os.path.join(LAB, "current")
        if not os.path.exists(f):
            return None
        name = open(f).read().strip()
        if not name:
            return None
        base = os.path.basename(name)
        for d in (LOCAL_PROBES, PROBES):
            full = os.path.join(d, base)
            if os.path.isfile(full):
                return full
        return None

    def _serve_file(self):
        full = self._resolve()
        probe = self._current_probe()
        if probe and full and full.endswith("index.html"):
            src = open(probe, encoding="utf-8", errors="replace").read()
            src = src.replace("</script", "<\\/script")
            page = ("<!doctype html><meta charset=\"utf-8\"><title>probe</title>"
                    "<body><script>\n" + src + "\n</script></body>")
            self._send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")
            return
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


def _log_conn(peer, ok, err=""):
    os.makedirs(RESULTS, exist_ok=True)
    rec = {"t": dt.datetime.now().isoformat(timespec="milliseconds"),
           "peer": peer, "tls_ok": ok, "error": err[:200]}
    with open(os.path.join(RESULTS, "conn.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"  conn {peer} tls_ok={ok} {err[:120]}")


class TLSServer(ThreadingHTTPServer):
    """Logs every accepted connection, including TLS handshake failures.

    Without this a cert rejection or a half-open connection is invisible: the
    request never reaches a handler, so the request log stays empty and it looks
    like the client never connected.
    """

    def __init__(self, addr, handler, ctx):
        self.ctx = ctx
        super().__init__(addr, handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        peer = addr[0] if addr else "?"
        try:
            conn = self.ctx.wrap_socket(sock, server_side=True)
            _log_conn(peer, True)
            return conn, addr
        except Exception as e:                                   # noqa: BLE001
            _log_conn(peer, False, f"{type(e).__name__}: {e}")
            try:
                sock.close()
            except OSError:
                pass
            raise


def run_https(port: int, verbose=True):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    httpd = TLSServer(("0.0.0.0", port), Handler, ctx)
    print(f"HTTPS listening on 0.0.0.0:{port}, serving {PAYLOAD}")
    print("connection log -> results/conn.jsonl  (logs TLS failures too)")
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
    ap.add_argument("--upstream", default="<resolver-ip>",
                    help="resolver to forward non-hijacked names to (default: the Pi-hole)")
    ap.add_argument("--dns-catchall", action="store_true",
                    help="answer every A query with --lan-ip and log every query name; "
                         "use when you do not yet know which host the guide asks for")
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
            # sendBeacon POSTs carry an empty body and put the tag in the URL path,
            # so the report must look at both.
            b, ua = (r["body"] or r.get("path", "")), r.get("ua", "")
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
            threads.append(threading.Thread(target=run_dns,
                                            args=(a.lan_ip, a.dns_port, True, a.dns_catchall,
                                                  a.upstream),
                                            daemon=True))
        for t in threads:
            t.start()
        if a.dns_catchall:
            print("DNS catch-all: every A query is answered with %s and logged." % a.lan_ip)
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
