#!/usr/bin/env python3
"""Two-origin server for the referrer-policy probe.

Serves the page on one authority and the subresources on another, logging the
Referer header of every request so the default policy of the build under test
can be read off the wire instead of inferred.

    python3 refsrv.py --page-port 8971 --res-port 8972 --out /tmp/ref.log

Page authority http://localhost:<page-port>, resource authority
http://127.0.0.1:<res-port>. Different host names, so every subresource is a
cross-origin request from a non-secure (http) referrer: for that shape
NoReferrerWhenDowngrade sends the full URL and StrictOriginWhenCrossOrigin
sends the origin only, which is the whole point of the probe.

GET /arm=<a|b|c> on the page port serves the page carrying one <img> per arm
(a = no attribute, b = referrerpolicy="unsafe-url", c = "no-referrer").
"""
import argparse
import http.server
import threading
import time

PAGE = """<!doctype html>
<meta charset=utf-8>
<title>ref</title>
<img id=a src="http://127.0.0.1:{res}/res.png?arm=a">
<img id=b src="http://127.0.0.1:{res}/res.png?arm=b" referrerpolicy="unsafe-url">
<img id=c src="http://127.0.0.1:{res}/res.png?arm=c" referrerpolicy="no-referrer">
<body>ok</body>
"""

# 1x1 transparent PNG
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000a49444154789c6360000002000154a24f6d000000'
    '0049454e44ae426082')


def make_handler(log, kind):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            stamp = time.strftime('%H:%M:%S')
            ref = self.headers.get('Referer', '<none>')
            with open(log, 'a') as f:
                f.write(f'{stamp} {kind} {self.path} referer={ref}\n')
            if kind == 'page':
                body = PAGE.format(res=ARGS.res_port).encode()
                ctype = 'text/html; charset=utf-8'
            else:
                body = PNG
                ctype = 'image/png'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    return H


def serve(port, kind, log):
    srv = http.server.ThreadingHTTPServer(('0.0.0.0', port), make_handler(log, kind))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--page-port', type=int, default=8971)
    ap.add_argument('--res-port', type=int, default=8972)
    ap.add_argument('--out', default='/tmp/ref.log')
    ap.add_argument('--seconds', type=int, default=40)
    ARGS = ap.parse_args()
    open(ARGS.out, 'w').close()
    serve(ARGS.page_port, 'page', ARGS.out)
    serve(ARGS.res_port, 'res', ARGS.out)
    print(f'serving page :{ARGS.page_port} res :{ARGS.res_port} -> {ARGS.out}', flush=True)
    time.sleep(ARGS.seconds)
