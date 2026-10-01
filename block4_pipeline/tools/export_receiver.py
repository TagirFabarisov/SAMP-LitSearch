"""Local receiver for database exports made in the browser pane.

The browser pane cannot save downloads, so a page hook posts the text of an export response
(e.g. Web of Science "Tab delimited file") to this receiver, which writes it unchanged to
data/raw/manual_exports/<source>/<name>. Listens on localhost only.

    python3 block4_pipeline/tools/export_receiver.py [port]
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / "manual_exports"


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        q = parse_qs(urlparse(self.path).query)
        source = (q.get("source") or ["unknown"])[0]
        name = (q.get("name") or ["export.txt"])[0]
        if "/" in source or "/" in name or ".." in source or ".." in name:
            self.send_response(400); self._cors(); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        out = ROOT / source / name
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            stem, suf = out.stem, out.suffix
            k = 2
            while (out.parent / ("%s_%d%s" % (stem, k, suf))).exists():
                k += 1
            out = out.parent / ("%s_%d%s" % (stem, k, suf))
        out.write_bytes(data)
        body = json.dumps({"saved": str(out), "bytes": len(data)}).encode()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("receiver: " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print("export receiver on http://127.0.0.1:%d -> %s" % (port, ROOT))
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
