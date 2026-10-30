import sys, http.server, socketserver
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map['.appcache'] = 'text/cache-manifest'
    def end_headers(self):
        if self.path.split('?')[0].endswith('.appcache'):
            self.send_header('Cache-Control', 'no-cache')
        http.server.SimpleHTTPRequestHandler.end_headers(self)
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
port = int(sys.argv[1])
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", port), H) as httpd:
    httpd.serve_forever()
