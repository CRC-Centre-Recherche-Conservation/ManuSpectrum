#!/usr/bin/env python3
"""Stand-in for Django (`web`) and Cantaloupe behind the edge nginx in test_edge.sh.

Usage: stub_upstream.py PORT NAME

By default every request is answered with JSON: the stub name, the method, the
raw request target (`self.path`, undecoded) and the headers received. The
answer also carries the headers Django sends on a page (X-Frame-Options,
X-Content-Type-Options, Referrer-Policy) and a Strict-Transport-Security
header Django would not, to prove that nginx keeps one owner per header.

Special routes:
  /en/files/<uuid>        FileView stand-ins (see FILE_REDIRECTS): 302 or 403
  /api/explorer/series.csv  three chunks, two seconds apart
  paths under /iiif/        add Access-Control-Allow-Origin: *
  X-Request-ID              echoed on every web answer, as Django does
  /big.csv                  2 KB of text/csv
"""

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILE_A = "00000000-0000-4000-8000-00000000000a"
FILE_B = "00000000-0000-4000-8000-00000000000b"
FILE_C = "00000000-0000-4000-8000-00000000000c"
FILE_D = "00000000-0000-4000-8000-00000000000d"
FILE_E = "00000000-0000-4000-8000-00000000000e"
FILE_F = "00000000-0000-4000-8000-00000000000f"

FILE_REDIRECTS = {
    FILE_A: (302, "/files/uploadedfiles/smoke%20file%20%C3%A9.csv"),
    FILE_B: (403, None),
    FILE_C: (302, "/files/archestemp/x.zip"),
    FILE_D: (302, "/files/uploadedfiles/..%2F..%2Fetc%2Fpasswd"),
    FILE_E: (302, "/files/export_deliverables/e.zip"),
    FILE_F: (302, "/files/uploadedfiles/missing.csv"),
}

DJANGO_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=1",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    name = "web"

    def log_message(self, *args):
        pass

    def reply(self, status, body=b"", content_type="application/json", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def drain_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def echo(self, extra=()):
        headers = {}
        for key, value in self.headers.items():
            headers.setdefault(key.lower(), value)
        payload = {
            "name": self.name,
            "method": self.command,
            "path": self.path,
            "headers": headers,
        }
        django = []
        if self.name != "cantaloupe":
            django = list(DJANGO_HEADERS.items())
            # Django's RequestIdMiddleware echoes the id: a response without it
            # was answered by nginx.
            django.append(("X-Request-ID", headers.get("x-request-id", "")))
        self.reply(200, json.dumps(payload).encode(), extra=django + list(extra))

    def stream_csv(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for index in range(3):
            chunk = f"chunk {index}\n".encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
            if index < 2:
                time.sleep(2)
        self.wfile.write(b"0\r\n\r\n")

    def handle_any(self):
        self.drain_body()
        path = self.path.split("?", 1)[0]
        match = re.fullmatch(r"/(?:en|fr)/files/([0-9a-f-]{36})", path)
        if match and match.group(1) in FILE_REDIRECTS:
            status, location = FILE_REDIRECTS[match.group(1)]
            extra = [("Location", location)] if location else []
            return self.reply(status, b"", "text/plain", extra)
        if path == "/api/explorer/series.csv":
            return self.stream_csv()
        if path == "/big.csv":
            return self.reply(200, b"a,b,c\n" * 400, "text/csv")
        if path.startswith("/iiif/"):
            return self.echo([("Access-Control-Allow-Origin", "*")])
        return self.echo()

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = handle_any


def main():
    port, name = int(sys.argv[1]), sys.argv[2]
    Handler.name = name
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
