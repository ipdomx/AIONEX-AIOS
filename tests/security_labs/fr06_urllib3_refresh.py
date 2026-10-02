"""Run with the isolated urllib3==2.8.0 interpreter, not production.

In-memory response parsing and a mocked TLS wrapper exercise the installed
library. No network, provider calls, credentials, GPU or production image.
"""
from __future__ import annotations

import http.client
import io
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import urllib3
from urllib3.connection import HTTPSConnection
from urllib3.exceptions import ProtocolError
from urllib3.response import HTTPResponse, _MAX_CHUNK_LINE_LENGTH


class MemorySocket:
    def __init__(self, body: bytes):
        self.stream = io.BytesIO(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + body)

    def makefile(self, mode: str):
        return self.stream


def response(body: bytes) -> HTTPResponse:
    raw = http.client.HTTPResponse(MemorySocket(body), method="GET")
    raw.begin()
    return HTTPResponse(body=raw, headers=dict(raw.getheaders()), original_response=raw, preload_content=False)


class SecurityRefresh(unittest.TestCase):
    def test_native_library_version(self):
        self.assertEqual(urllib3.__version__, "2.8.0")

    def test_regular_chunked_response_still_reads(self):
        with response(b"4\r\ntest\r\n0\r\n\r\n") as result:
            self.assertEqual(b"".join(result.read_chunked()), b"test")

    def test_oversized_chunk_extension_is_rejected(self):
        with response(b"1;" + b"x" * (_MAX_CHUNK_LINE_LENGTH + 16) + b"\r\na\r\n0\r\n\r\n") as result:
            with self.assertRaisesRegex(ProtocolError, "maximum allowed length"):
                list(result.read_chunked())

    def test_target_policy_does_not_override_proxy_tls_policy(self):
        proxy_context = ssl.create_default_context()
        target_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        target_context.check_hostname = False
        target_context.verify_mode = ssl.CERT_NONE
        proxy_config = SimpleNamespace(ssl_context=proxy_context, assert_hostname="proxy.test.invalid", assert_fingerprint=None)
        connection = HTTPSConnection("target.test.invalid", cert_reqs=ssl.CERT_NONE,
                                     ssl_context=target_context, proxy_config=proxy_config)
        socket_marker = object()
        captured = {}

        def wrapper(sock, **kwargs):
            captured.update(kwargs)
            self.assertIs(sock, socket_marker)
            return SimpleNamespace(socket=socket_marker, is_verified=True)

        with patch("urllib3.connection._ssl_wrap_socket_and_match_hostname", side_effect=wrapper):
            self.assertIs(connection._connect_tls_proxy("proxy.test.invalid", socket_marker), socket_marker)
        self.assertIs(captured["ssl_context"], proxy_context)
        self.assertEqual(captured["cert_reqs"], ssl.CERT_REQUIRED)
        self.assertEqual(captured["server_hostname"], "proxy.test.invalid")
        self.assertEqual(captured["assert_hostname"], "proxy.test.invalid")
        self.assertIsNone(captured["cert_file"])
        self.assertIsNone(captured["key_file"])
        self.assertEqual(proxy_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(proxy_context.check_hostname)
        self.assertEqual(target_context.verify_mode, ssl.CERT_NONE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
