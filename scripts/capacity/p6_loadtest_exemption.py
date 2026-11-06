#!/usr/bin/env python3
"""Render the time-boxed Nginx rate-limit exemption for the 6.1 load generator.

Every virtual user of the 6.1 test comes from one generator IP, so the per-IP
``api_per_ip`` (20 r/s), ``auth_per_ip`` (5 r/min) and ``connections_per_ip``
zones would measure the limiter, not the platform.  This renders the
``exempt.conf`` consumed by ``web-dashboard/docker/nginx-p6-loadtest-entrypoint.sh``:
only public unicast /32 or /128 addresses, at most four, with a mandatory
expiry no more than 8 hours ahead.  Nginx refuses to start once it expires.

Writes nothing unless --output is given; the file is create-only 0644 (Nginx
runs as uid 101 and must read it; it holds no secret).
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import sys
import time
from pathlib import Path

MAX_ADDRESSES = 4
MAX_WINDOW_SECONDS = 8 * 3600


class ExemptionError(ValueError):
    pass


def validate_address(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(raw.strip())
    except ValueError as exc:
        raise ExemptionError(f"not an IP address: {raw!r}") from exc
    if (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
        or not address.is_global
    ):
        raise ExemptionError(f"{address} is not a public unicast address")
    return address


def render(addresses: list[str], *, expires_epoch: int, run_id: str, now: float | None = None) -> str:
    current = time.time() if now is None else now
    if not addresses or len(addresses) > MAX_ADDRESSES:
        raise ExemptionError(f"between 1 and {MAX_ADDRESSES} addresses are required")
    if not current < expires_epoch <= current + MAX_WINDOW_SECONDS:
        raise ExemptionError("expiry must be in the future and at most 8 hours away")
    if not run_id.startswith("p6-") or not all(c.isalnum() or c in "-" for c in run_id) or len(run_id) > 40:
        raise ExemptionError("run id must be the p6 run id")
    parsed = sorted({validate_address(item) for item in addresses}, key=lambda a: (a.version, int(a)))
    lines = [
        f"# P6 load-test window {run_id}",
        f"# expires_epoch={int(expires_epoch)}",
    ]
    for address in parsed:
        suffix = 32 if address.version == 4 else 128
        lines.append(f"{address.compressed}/{suffix} 1;")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", action="append", required=True, help="load-generator public IP")
    parser.add_argument("--hours", type=float, default=4.0)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        text = render(args.address, expires_epoch=int(time.time() + args.hours * 3600), run_id=args.run_id)
    except ExemptionError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.output is None:
        print(text, end="")
        return 0
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(text)
    print(f"written {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
