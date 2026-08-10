from __future__ import annotations

import html
import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "AIONEX Fixed Acceptance Fixture", "version": "1.0"},
    "security": [{"bearerAuth": []}],
    "components": {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
    },
    "paths": {
        "/api/projects/{project_id}/transfer": {
            "post": {
                "parameters": [
                    {
                        "name": "project_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Transferred"},
                    "401": {"description": "Unauthenticated"},
                    "403": {"description": "Forbidden"},
                },
            }
        },
        "/api/users/{user_id}/profile": {
            "get": {
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Profile"},
                    "401": {"description": "Unauthenticated"},
                    "403": {"description": "Forbidden"},
                },
            }
        },
    },
}

USERS = {
    "1": {"id": "1", "email": "alice@example.invalid", "role": "user"},
    "2": {"id": "2", "email": "bob@example.invalid", "role": "user"},
}


def safe_lookup(query: str):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    connection.executemany(
        "INSERT INTO users(id, name) VALUES (?, ?)", [(1, "alice"), (2, "bob")]
    )
    try:
        return connection.execute(
            "SELECT id, name FROM users WHERE name = ?", (query,)
        ).fetchall()
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "AIONEXAcceptanceFixture/1.0"

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; font-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # The fixture runs over HTTP inside an isolated Docker network, so Secure is
        # represented for header-policy validation even though browsers would not send it.
        self.send_header(
            "Set-Cookie",
            "sessionid=acceptance-fixture; Path=/; Secure; HttpOnly; SameSite=Strict",
        )
        self.end_headers()
        self.wfile.write(raw)

    @staticmethod
    def _authorized(headers) -> bool:
        return headers.get("Authorization") == "Bearer acceptance-user-1"

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            body = """<!doctype html><html><body>
            <h1>AIONEX Security Acceptance Fixture</h1>
            <a href='/reflect?name=guest'>reflection</a>
            <a href='/search?q=alice'>search</a>
            <a href='/openapi.json'>openapi</a>
            </body></html>"""
            self._send(HTTPStatus.OK, body)
            return
        if parsed.path == "/reflect":
            name = html.escape(params.get("name", [""])[0], quote=True)
            self._send(HTTPStatus.OK, f"<html><body>Hello {name}</body></html>")
            return
        if parsed.path == "/search":
            query = params.get("q", [""])[0]
            rows = safe_lookup(query)
            self._send(HTTPStatus.OK, json.dumps({"rows": rows}), "application/json")
            return
        if parsed.path.startswith("/api/users/") and parsed.path.endswith("/profile"):
            if not self._authorized(self.headers):
                self._send(HTTPStatus.UNAUTHORIZED, json.dumps({"error": "unauthorized"}), "application/json")
                return
            user_id = parsed.path.split("/")[3]
            if user_id != "1":
                self._send(HTTPStatus.FORBIDDEN, json.dumps({"error": "forbidden"}), "application/json")
                return
            self._send(HTTPStatus.OK, json.dumps(USERS[user_id]), "application/json")
            return
        if parsed.path == "/openapi.json":
            self._send(HTTPStatus.OK, json.dumps(OPENAPI), "application/json")
            return
        if parsed.path == "/health":
            self._send(HTTPStatus.OK, json.dumps({"status": "ok"}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/transfer"):
            if not self._authorized(self.headers):
                self._send(HTTPStatus.UNAUTHORIZED, json.dumps({"error": "unauthorized"}), "application/json")
                return
            self._send(HTTPStatus.OK, json.dumps({"ok": True}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8088), Handler).serve_forever()
