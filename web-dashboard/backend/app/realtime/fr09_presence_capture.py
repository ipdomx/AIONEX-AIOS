"""Controlled FR09 server-presence collector (never a client-supplied report).

The collector can be invoked inside an isolated or independently approved
backend runtime. It requests atomic Redis snapshots emitted by connections
that passed the existing websocket authorization and signs the evidence with
a separate 0600 operator-owned key. It does not create user sessions, send
provider requests, or grant any release approval.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.realtime.fr09_authenticated_presence import (
    SOURCE,
    ServerPresenceRecorder,
    read_private_key,
)

# 32 samples at 29.5 second intervals cover at least 914.5 seconds. The
# schedule tolerates <=0.5s ordinary collector jitter before the existing
# <=30 second verifier rejects a gap. A missed slot is a HOLD, never a fill.
SAMPLE_COUNT = 32
SAMPLE_INTERVAL_SECONDS = 29.5
MIN_STEADY_SECONDS = 900
MAX_GAP_SECONDS = 30.001


def _signed_content(
    run_id: str, samples: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(samples) != SAMPLE_COUNT:
        raise ValueError("FR09 complete sample inventory required")
    start, end = samples[0]["at_epoch"], samples[-1]["at_epoch"]
    if (
        type(start) not in (int, float)
        or type(end) not in (int, float)
        or not math.isfinite(start)
        or not math.isfinite(end)
        or end - start < MIN_STEADY_SECONDS
    ):
        raise ValueError("FR09 sustained window was not observed")
    previous = None
    for row in samples:
        timestamp = row.get("at_epoch")
        if (
            type(timestamp) not in (int, float)
            or not math.isfinite(timestamp)
            or type(row.get("authenticated_sessions")) is not int
            or type(row.get("distinct_authenticated_users")) is not int
            or row["authenticated_sessions"] < 0
            or row["distinct_authenticated_users"] < 0
            or row["distinct_authenticated_users"] > row["authenticated_sessions"]
            or (previous is not None and not 0 < timestamp - previous <= MAX_GAP_SECONDS)
        ):
            raise ValueError("FR09 signed collector observations inconsistent")
        previous = timestamp
    return {
        "run_id": run_id,
        "window_start_epoch": start,
        "window_end_epoch": end,
        "source": SOURCE,
        "samples": samples,
    }


@dataclass(frozen=True, slots=True)
class SignedPresenceReceipt:
    run_id: str
    window_start_epoch: float
    window_end_epoch: float
    server_concurrency: dict[str, Any]


async def collect_signed_presence(
    recorder: ServerPresenceRecorder,
    *,
    signing_key_file: str,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> SignedPresenceReceipt:
    """Collect genuine Redis observations, with no caller-provided counters."""
    signing_key = read_private_key(signing_key_file)
    if hmac.compare_digest(signing_key, recorder.config.identity_key):
        raise ValueError("independent FR09 signing and identity keys required")
    start_tick = monotonic()
    points: list[dict[str, Any]] = []
    for index in range(SAMPLE_COUNT):
        target = start_tick + index * SAMPLE_INTERVAL_SECONDS
        delay = target - monotonic()
        if delay > 0:
            await sleep(delay)
        measurement = await recorder.sample()
        points.append(measurement)
    payload = _signed_content(recorder.config.run_id, points)
    signature = hmac.new(
        signing_key,
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return SignedPresenceReceipt(
        run_id=recorder.config.run_id,
        window_start_epoch=payload["window_start_epoch"],
        window_end_epoch=payload["window_end_epoch"],
        server_concurrency={
            "run_id": recorder.config.run_id,
            "source": SOURCE,
            "samples": points,
            "hmac_sha256": signature,
        },
    )
