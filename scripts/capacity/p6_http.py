"""Minimal stdlib asyncio HTTP/1.1 + WebSocket client for the P6 launch gates.

Used by ``p6_mixed_load.py`` (6.1) and ``p6_stream_fault_matrix.py`` (6.3).
It has no third-party dependency so a separate load-generator machine needs
only Python 3.11+.  One ``HttpConnection`` is one keep-alive TCP/TLS
connection, which models one browser tab per virtual user.

Nothing in this module chooses a target; the callers enforce the target
allow-list and stop conditions.  Response bodies are bounded.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import struct
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

MAX_HEADER_BYTES = 64 * 1024
MAX_BODY_BYTES = 4 * 1024 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class HttpClientError(Exception):
    """Transport-level failure (connect, TLS, protocol, timeout)."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: float

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


@dataclass(frozen=True)
class Origin:
    scheme: str
    host: str
    port: int

    @classmethod
    def parse(cls, url: str) -> "Origin":
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("origin must be an http(s) URL with a host")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("origin must not carry credentials, query or fragment")
        if parts.path not in {"", "/"}:
            raise ValueError("origin must not carry a path")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return cls(parts.scheme, parts.hostname.lower(), port)

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"


def _ssl_context(origin: Origin, ca_file: str | None) -> ssl.SSLContext | None:
    if origin.scheme != "https":
        return None
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


async def _read_head(reader: asyncio.StreamReader) -> tuple[int, dict[str, str]]:
    try:
        raw = await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError as exc:
        raise HttpClientError("header_too_large") from exc
    except asyncio.IncompleteReadError as exc:
        raise HttpClientError("connection_closed") from exc
    if len(raw) > MAX_HEADER_BYTES:
        raise HttpClientError("header_too_large")
    lines = raw.decode("latin-1").split("\r\n")
    status_line = lines[0].split(" ", 2)
    if len(status_line) < 2 or not status_line[0].startswith("HTTP/1."):
        raise HttpClientError("bad_status_line")
    try:
        status = int(status_line[1])
    except ValueError as exc:
        raise HttpClientError("bad_status_line") from exc
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        key = name.strip().lower()
        value = value.strip()
        headers[key] = f"{headers[key]}, {value}" if key in headers else value
    return status, headers


async def _read_body(reader: asyncio.StreamReader, headers: dict[str, str], method: str, status: int) -> bytes:
    if method == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return b""
    if "chunked" in headers.get("transfer-encoding", "").lower():
        chunks: list[bytes] = []
        total = 0
        while True:
            size_line = await reader.readline()
            try:
                size = int(size_line.split(b";", 1)[0].strip(), 16)
            except ValueError as exc:
                raise HttpClientError("bad_chunk") from exc
            if size == 0:
                # trailer section
                while (await reader.readline()) not in (b"\r\n", b""):
                    continue
                return b"".join(chunks)
            total += size
            if total > MAX_BODY_BYTES:
                raise HttpClientError("body_too_large")
            chunks.append(await reader.readexactly(size))
            await reader.readexactly(2)
    length = headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError as exc:
            raise HttpClientError("bad_content_length") from exc
        if size < 0 or size > MAX_BODY_BYTES:
            raise HttpClientError("body_too_large")
        return await reader.readexactly(size)
    data = await reader.read(MAX_BODY_BYTES + 1)
    if len(data) > MAX_BODY_BYTES:
        raise HttpClientError("body_too_large")
    return data


@dataclass
class HttpConnection:
    """One keep-alive HTTP/1.1 connection (re-opened transparently)."""

    origin: Origin
    timeout: float = 30.0
    ca_file: str | None = None
    user_agent: str = "aionex-p6-launch-gate/1"
    _reader: asyncio.StreamReader | None = field(default=None, init=False, repr=False)
    _writer: asyncio.StreamWriter | None = field(default=None, init=False, repr=False)
    connects: int = field(default=0, init=False)

    async def _open(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.origin.host,
                    self.origin.port,
                    ssl=_ssl_context(self.origin, self.ca_file),
                    server_hostname=self.origin.host if self.origin.scheme == "https" else None,
                    limit=MAX_HEADER_BYTES,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise HttpClientError("connect_timeout") from exc
        except ssl.SSLError as exc:
            raise HttpClientError("tls_error", type(exc).__name__) from exc
        except OSError as exc:
            raise HttpClientError("connect_error", type(exc).__name__) from exc
        self.connects += 1

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except (asyncio.TimeoutError, OSError, ssl.SSLError):
                return

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        if not path.startswith("/"):
            raise ValueError("path must be absolute")
        for attempt in (0, 1):
            fresh = self._writer is None
            if fresh:
                await self._open()
            started = time.perf_counter()
            try:
                return await asyncio.wait_for(
                    self._exchange(method, path, headers or {}, body, started),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError as exc:
                await self.close()
                raise HttpClientError("request_timeout") from exc
            except HttpClientError as exc:
                await self.close()
                # A stale keep-alive socket closed by the peer is retried once,
                # only when nothing could have been processed (fresh=False).
                if exc.kind == "connection_closed" and not fresh and attempt == 0:
                    continue
                raise
            except (OSError, ssl.SSLError) as exc:
                await self.close()
                if not fresh and attempt == 0:
                    continue
                raise HttpClientError("io_error", type(exc).__name__) from exc
        raise HttpClientError("connection_closed")

    async def _exchange(
        self, method: str, path: str, headers: dict[str, str], body: bytes | None, started: float
    ) -> HttpResponse:
        assert self._reader is not None and self._writer is not None
        lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.origin.host_header}",
            f"User-Agent: {self.user_agent}",
            "Accept: application/json",
            "Connection: keep-alive",
        ]
        for name, value in headers.items():
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise ValueError("header injection rejected")
            lines.append(f"{name}: {value}")
        if body is not None:
            lines.append(f"Content-Length: {len(body)}")
        self._writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (body or b""))
        await self._writer.drain()
        status, response_headers = await _read_head(self._reader)
        payload = await _read_body(self._reader, response_headers, method, status)
        elapsed = (time.perf_counter() - started) * 1000.0
        if response_headers.get("connection", "").lower() == "close":
            await self.close()
        return HttpResponse(status, response_headers, payload, elapsed)


def json_body(payload: Any) -> tuple[dict[str, str], bytes]:
    return {"Content-Type": "application/json"}, json.dumps(payload, separators=(",", ":")).encode()


def form_body(payload: dict[str, str]) -> tuple[dict[str, str], bytes]:
    return (
        {"Content-Type": "application/x-www-form-urlencoded"},
        urllib.parse.urlencode(payload).encode(),
    )


# --------------------------------------------------------------------------- WebSocket


class WebSocketClosed(Exception):
    def __init__(self, code: int | None) -> None:
        super().__init__(f"websocket closed: {code}")
        self.code = code


def ws_accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def encode_ws_frame(opcode: int, payload: bytes, *, mask_key: bytes | None = None) -> bytes:
    """Encode one final, client-masked frame (RFC 6455 section 5.2)."""
    mask_key = mask_key if mask_key is not None else os.urandom(4)
    if len(mask_key) != 4:
        raise ValueError("mask key must be 4 bytes")
    head = bytearray([0x80 | (opcode & 0x0F)])
    size = len(payload)
    if size < 126:
        head.append(0x80 | size)
    elif size < 65536:
        head.append(0x80 | 126)
        head += struct.pack("!H", size)
    else:
        head.append(0x80 | 127)
        head += struct.pack("!Q", size)
    masked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
    return bytes(head) + mask_key + masked


async def read_ws_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first, second = await reader.readexactly(2)
    opcode = first & 0x0F
    size = second & 0x7F
    if size == 126:
        (size,) = struct.unpack("!H", await reader.readexactly(2))
    elif size == 127:
        (size,) = struct.unpack("!Q", await reader.readexactly(8))
    if size > MAX_BODY_BYTES:
        raise HttpClientError("ws_frame_too_large")
    mask = await reader.readexactly(4) if second & 0x80 else None
    data = await reader.readexactly(size)
    if mask:
        data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    return opcode, data


@dataclass
class WebSocketConnection:
    origin: Origin
    path: str
    timeout: float = 30.0
    ca_file: str | None = None
    _reader: asyncio.StreamReader | None = field(default=None, init=False, repr=False)
    _writer: asyncio.StreamWriter | None = field(default=None, init=False, repr=False)
    handshake_ms: float = field(default=0.0, init=False)

    async def connect(self, headers: dict[str, str] | None = None) -> None:
        started = time.perf_counter()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.origin.host,
                    self.origin.port,
                    ssl=_ssl_context(self.origin, self.ca_file),
                    server_hostname=self.origin.host if self.origin.scheme == "https" else None,
                    limit=MAX_HEADER_BYTES,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise HttpClientError("connect_timeout") from exc
        except (OSError, ssl.SSLError) as exc:
            raise HttpClientError("connect_error", type(exc).__name__) from exc
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            f"GET {self.path} HTTP/1.1",
            f"Host: {self.origin.host_header}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            f"Origin: {self.origin.scheme}://{self.origin.host_header}",
        ]
        for name, value in (headers or {}).items():
            if "\r" in value or "\n" in value:
                raise ValueError("header injection rejected")
            lines.append(f"{name}: {value}")
        self._writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await self._writer.drain()
        status, response_headers = await asyncio.wait_for(_read_head(self._reader), self.timeout)
        if status != 101 or response_headers.get("sec-websocket-accept") != ws_accept_key(key):
            await self.close()
            raise HttpClientError("ws_handshake_rejected", str(status))
        self.handshake_ms = (time.perf_counter() - started) * 1000.0

    async def send_text(self, text: str) -> None:
        assert self._writer is not None
        self._writer.write(encode_ws_frame(0x1, text.encode()))
        await self._writer.drain()

    async def receive(self, timeout: float) -> str:
        """Return the next text message; answer pings; raise on close."""
        assert self._reader is not None and self._writer is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            opcode, data = await asyncio.wait_for(read_ws_frame(self._reader), remaining)
            if opcode == 0x9:  # ping
                self._writer.write(encode_ws_frame(0xA, data))
                await self._writer.drain()
            elif opcode == 0x8:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None
                await self.close()
                raise WebSocketClosed(code)
            elif opcode in (0x1, 0x0):
                return data.decode("utf-8", errors="replace")

    async def close(self, code: int = 1000) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is None:
            return
        try:
            writer.write(encode_ws_frame(0x8, struct.pack("!H", code)))
            await asyncio.wait_for(writer.drain(), timeout=1)
        except (OSError, ssl.SSLError, asyncio.TimeoutError, RuntimeError):
            writer.close()
            return
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2)
        except (asyncio.TimeoutError, OSError, ssl.SSLError):
            return

    def abort(self) -> None:
        """Drop the TCP connection without a close frame (fault injection)."""
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            transport = writer.transport
            transport.abort()
