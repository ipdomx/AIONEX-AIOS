from __future__ import annotations

import html
import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODE = "vulnerable"
USERS = {
    "1": {"id": "1", "email": "alice@example.invalid", "role": "user"},
    "2": {"id": "2", "email": "bob@example.invalid", "role": "user"},
}


def openapi_spec() -> dict:
    if MODE == "vulnerable":
        return {
            "openapi": "3.0.3",
            "info": {"title": "AIONEX Vulnerable Acceptance Fixture", "version": "1.0"},
            "paths": {
                "/api/projects/{project_id}/transfer": {
                    "post": {
                        "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "Transferred"}},
                    }
                },
                "/api/users/{user_id}/profile": {
                    "get": {
                        "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "Profile"}},
                    }
                },
            },
        }
    return {
        "openapi": "3.0.3",
        "info": {"title": "AIONEX Fixed Acceptance Fixture", "version": "1.0"},
        "security": [{"bearerAuth": []}],
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
        "paths": {
            "/api/projects/{project_id}/transfer": {
                "post": {
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Transferred"}, "401": {"description": "Unauthenticated"}, "403": {"description": "Forbidden"}},
                }
            },
            "/api/users/{user_id}/profile": {
                "get": {
                    "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Profile"}, "401": {"description": "Unauthenticated"}, "403": {"description": "Forbidden"}},
                }
            },
        },
    }


def safe_lookup(query: str):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    connection.executemany("INSERT INTO users(id, name) VALUES (?, ?)", [(1, "alice"), (2, "bob")])
    try:
        if MODE == "vulnerable":
            lowered = query.lower()
            # Deterministically emulate the observable behavior of a vulnerable
            # search endpoint without executing user-controlled SQL in the test
            # harness itself. This lets DAST prove its detection path while the
            # repository remains safe for CodeQL and accidental execution.
            if " or " in lowered and "1" in lowered:
                return connection.execute("SELECT id, name FROM users ORDER BY id").fetchall()
            if "'" in query or '"' in query:
                raise sqlite3.OperationalError("near quote: syntax error")
        return connection.execute("SELECT id, name FROM users WHERE name = ?", (query,)).fetchall()
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "AIONEXAcceptanceRuntime/1.0"

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        if MODE == "vulnerable":
            self.send_header("Set-Cookie", "sessionid=acceptance-fixture; Path=/")
        else:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; font-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Set-Cookie", "sessionid=acceptance-fixture; Path=/; Secure; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(raw)

    @staticmethod
    def _authorized(headers) -> bool:
        return headers.get("Authorization") == "Bearer acceptance-user-1"

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            self._send(
                HTTPStatus.OK,
                "<html><body><h1>AIONEX Security Acceptance Fixture</h1>"
                "<a href='/reflect?name=guest'>reflection</a> "
                "<a href='/search?q=alice'>search</a> "
                "<a href='/api/users/1/profile'>profile</a> "
                "<a href='/openapi.json'>openapi</a></body></html>",
            )
            return
        if parsed.path == "/reflect":
            name = params.get("name", [""])[0]
            rendered = name if MODE == "vulnerable" else html.escape(name, quote=True)
            self._send(HTTPStatus.OK, f"<html><body>Hello {rendered}</body></html>")
            return
        if parsed.path == "/search":
            query = params.get("q", [""])[0]
            try:
                rows = safe_lookup(query)
                self._send(HTTPStatus.OK, json.dumps({"rows": rows}), "application/json")
            except sqlite3.Error as exc:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, json.dumps({"error": f"sqlite error: {type(exc).__name__}: {exc}"}), "application/json")
            return
        if parsed.path.startswith("/api/users/") and parsed.path.endswith("/profile"):
            user_id = parsed.path.split("/")[3]
            if MODE == "fixed":
                if not self._authorized(self.headers):
                    self._send(HTTPStatus.UNAUTHORIZED, json.dumps({"error": "unauthorized"}), "application/json")
                    return
                if user_id != "1":
                    self._send(HTTPStatus.FORBIDDEN, json.dumps({"error": "forbidden"}), "application/json")
                    return
            profile = USERS.get(user_id)
            if profile is None:
                self._send(HTTPStatus.NOT_FOUND, json.dumps({"error": "not found"}), "application/json")
            else:
                self._send(HTTPStatus.OK, json.dumps(profile), "application/json")
            return
        if parsed.path == "/openapi.json":
            self._send(HTTPStatus.OK, json.dumps(openapi_spec()), "application/json")
            return
        if MODE == "vulnerable" and parsed.path == "/.git/config":
            self._send(HTTPStatus.OK, "[core]\nrepositoryformatversion = 0\n", "text/plain")
            return
        if parsed.path == "/health":
            self._send(HTTPStatus.OK, json.dumps({"status": "ok", "mode": MODE}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def do_POST(self):
        global MODE
        parsed = urlparse(self.path)
        if parsed.path == "/__acceptance__/fix" and self.headers.get("X-AIONEX-Acceptance") == "1":
            MODE = "fixed"
            self._send(HTTPStatus.OK, json.dumps({"mode": MODE}), "application/json")
            return
        if parsed.path == "/__acceptance__/reset" and self.headers.get("X-AIONEX-Acceptance") == "1":
            MODE = "vulnerable"
            self._send(HTTPStatus.OK, json.dumps({"mode": MODE}), "application/json")
            return
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/transfer"):
            if MODE == "fixed" and not self._authorized(self.headers):
                self._send(HTTPStatus.UNAUTHORIZED, json.dumps({"error": "unauthorized"}), "application/json")
                return
            self._send(HTTPStatus.OK, json.dumps({"ok": True}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
