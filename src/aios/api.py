from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .kernel import AIOSKernel


class Handler(BaseHTTPRequestHandler):
    kernel = AIOSKernel()

    def send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == '/health':
            self.send_json(200, self.kernel.status())
        elif self.path == '/projects':
            self.send_json(200, self.kernel.projects.list())
        else:
            self.send_json(404, {'error': 'not_found'})

    def do_POST(self) -> None:
        length = int(self.headers.get('Content-Length', '0'))
        data = json.loads(self.rfile.read(length) or b'{}')
        if self.path == '/analyze':
            self.send_json(200, self.kernel.analyze(data.get('request', ''), data.get('project')))
        elif self.path == '/chat':
            self.send_json(200, {'response': self.kernel.chat(data.get('request', ''), data.get('project'))})
        else:
            self.send_json(404, {'error': 'not_found'})


def main() -> None:
    host = os.environ.get('AIOS_API_HOST', '127.0.0.1')
    port = int(os.environ.get('AIOS_API_PORT', '8080'))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
