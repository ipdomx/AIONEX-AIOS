from __future__ import annotations

import json
import pickle
import sqlite3
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Intentionally fake acceptance-lab credential. It is not valid anywhere.
api_key = "AIONEX_FAKE_ACCEPTANCE_KEY_1234567890"

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "AIONEX Vulnerable Acceptance Fixture", "version": "1.0"},
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
                "responses": {"200": {"description": "Transferred"}},
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
                "responses": {"200": {"description": "Profile"}},
            }
        },
    },
}

USERS = {
    "1": {"id": "1", "email": "alice@example.invalid", "role": "user"},
    "2": {"id": "2", "email": "bob@example.invalid", "role": "user"},
}


def dangerous_eval(user_input: str):
    return eval(user_input)


def dangerous_shell(user_input: str):
    return subprocess.run(user_input, shell=True, capture_output=True, text=True)


def dangerous_pickle(payload: bytes):
    return pickle.loads(payload)


def disabled_tls_example(url: str):
    import requests

    return requests.get(url, verify=False, timeout=2)


class Handler(BaseHTTPRequestHandler):
    server_version = "AIONEXAcceptanceFixture/0.1"

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Set-Cookie", "sessionid=acceptance-fixture; Path=/")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            body = """<!doctype html><html><body>
            <h1>AIONEX Security Acceptance Fixture</h1>
            <a href='/reflect?name=guest'>reflection</a>
            <a href='/search?q=alice'>search</a>
            <a href='/api/users/1/profile'>profile</a>
            <a href='/openapi.json'>openapi</a>
            </body></html>"""
            self._send(HTTPStatus.OK, body)
            return
        if parsed.path == "/reflect":
            name = params.get("name", [""])[0]
            # Intentional reflected XSS for the isolated acceptance lab.
            self._send(HTTPStatus.OK, f"<html><body>Hello {name}</body></html>")
            return
        if parsed.path == "/search":
            query = params.get("q", [""])[0]
            connection = sqlite3.connect(":memory:")
            connection.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            connection.executemany(
                "INSERT INTO users(id, name) VALUES (?, ?)", [(1, "alice"), (2, "bob")]
            )
            try:
                lowered = query.lower()
                # Emulate vulnerable SQL endpoint behavior without ever executing
                # user-controlled SQL inside the repository fixture itself.
                if " or " in lowered and "1" in lowered:
                    rows = connection.execute("SELECT id, name FROM users ORDER BY id").fetchall()
                elif "'" in query or '"' in query:
                    raise sqlite3.OperationalError("near quote: syntax error")
                else:
                    rows = connection.execute(
                        "SELECT id, name FROM users WHERE name = ?", (query,)
                    ).fetchall()
                body = json.dumps({"rows": rows})
                self._send(HTTPStatus.OK, body, "application/json")
            except sqlite3.Error as exc:
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    json.dumps({"error": f"sqlite error: {type(exc).__name__}: {exc}"}),
                    "application/json",
                )
            finally:
                connection.close()
            return
        if parsed.path.startswith("/api/users/") and parsed.path.endswith("/profile"):
            user_id = parsed.path.split("/")[3]
            profile = USERS.get(user_id)
            if profile is None:
                self._send(HTTPStatus.NOT_FOUND, json.dumps({"error": "not found"}), "application/json")
            else:
                # Intentional IDOR: no authentication or object ownership check.
                self._send(HTTPStatus.OK, json.dumps(profile), "application/json")
            return
        if parsed.path == "/openapi.json":
            self._send(HTTPStatus.OK, json.dumps(OPENAPI), "application/json")
            return
        if parsed.path == "/.git/config":
            self._send(HTTPStatus.OK, "[core]\nrepositoryformatversion = 0\n", "text/plain")
            return
        if parsed.path == "/health":
            self._send(HTTPStatus.OK, json.dumps({"status": "ok"}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/projects/") and parsed.path.endswith("/transfer"):
            # Intentional unauthenticated state-changing operation.
            self._send(HTTPStatus.OK, json.dumps({"ok": True}), "application/json")
            return
        self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain")

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
