#!/usr/bin/env python3
"""Fast, dependency-free liveness probes for file-heartbeat AIOS workers.

Docker healthchecks must not import the full application/service stack every
30 seconds just to read a heartbeat. This script does not access credentials,
networks or databases; it preserves the workers' existing status and age
requirements and fails closed on malformed/oversized receipts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time
from typing import NamedTuple


MAX_HEALTH_BYTES = 64 * 1024


class Policy(NamedTuple):
    env_var: str
    default_path: str
    status: str
    minimum_age: float
    maximum_age: float


POLICIES = {
    "three-d": Policy(
        "THREE_D_WORKER_HEALTH_FILE",
        "/tmp/aionex-three-d-worker-health.json",
        "ok",
        -30.0,
        120.0,
    ),
    "user-telegram": Policy(
        "AIOS_USER_TELEGRAM_HEALTH_FILE",
        "/tmp/aionex-user-telegram-worker-health.json",
        "running",
        0.0,
        120.0,
    ),
}


def check_heartbeat(
    path: Path, policy: Policy, *, now_epoch: float | None = None
) -> bool:
    """Use precisely the same status/heartbeat windows as the source workers."""
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_HEALTH_BYTES + 1)
        if len(raw) > MAX_HEALTH_BYTES:
            return False
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("status") != policy.status:
            return False
        checked_at = float(payload["checked_at_epoch"])
        observed_at = time.time() if now_epoch is None else float(now_epoch)
        if not (math.isfinite(checked_at) and math.isfinite(observed_at)):
            return False
        if checked_at <= 0:
            return False
        age = observed_at - checked_at
        return policy.minimum_age <= age <= policy.maximum_age
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=tuple(POLICIES), required=True)
    args = parser.parse_args()
    policy = POLICIES[args.kind]
    path = Path(os.environ.get(policy.env_var) or policy.default_path)
    return 0 if check_heartbeat(path, policy) else 1


if __name__ == "__main__":
    raise SystemExit(main())
