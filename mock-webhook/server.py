#!/usr/bin/env python3
"""Local webhook sink for development and integration tests. Never used on the public internet."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE: list[dict] = []
FAIL_UNTIL = int(os.environ.get("FAIL_UNTIL", "0"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "received": len(STORE)})
            return
        if self.path == "/received":
            self._send(200, {"events": STORE})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        if self.path == "/fail":
            self._send(500, {"error": "forced"})
            return
        if FAIL_UNTIL and len(STORE) < FAIL_UNTIL:
            self._send(503, {"error": "unavailable"})
            return
        STORE.append({"idempotency_key": self.headers.get("Idempotency-Key"), "payload": payload})
        self._send(200, {"ok": True})

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8088"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
