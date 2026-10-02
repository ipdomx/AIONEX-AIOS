#!/usr/bin/env python3
"""Bind one short-lived FR-06 C5E activation receipt to current runtime evidence.

This module is intentionally read/verify only. It never changes swap, mounts,
systemd, Docker, maintenance admission, providers, or application state.

A successful result is a typed BoundContext consumed by existing C5E journal
adapters. It is not itself a kernel-effect permit beyond the bounded activation
receipt and does not claim reboot recovery.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from scripts.security.fr06c5_memory_transaction import BoundContext

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ACTIVATION_FIELDS = {
    "schema", "source_commit", "boot_id", "operation_id", "generation",
    "full_host_closure_receipt_sha256", "host_state_receipt_sha256",
    "preflight_sha256", "boot_graph_sha256", "issued_at_epoch",
    "expires_at_epoch", "maintenance_closed", "full_host_closure",
    "production_activation_authorized", "receipt_sha256",
}
MAINTENANCE_FIELDS = {
    "operation_id", "generation", "status", "enabled", "full_host_closure",
}


class RuntimeAuthorityBlocked(RuntimeError):
    """Current runtime evidence cannot support a C5E bound context."""


def _canon(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file(path: Path, *, max_bytes: int = 1 << 20) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimeAuthorityBlocked("absolute evidence path required")
    try:
        with path.open("rb") as stream:
            value = stream.read(max_bytes + 1)
    except OSError as exc:
        raise RuntimeAuthorityBlocked("evidence file unavailable") from exc
    if not value or len(value) > max_bytes:
        raise RuntimeAuthorityBlocked("evidence file empty or exceeds bound")
    return value


def _json_bytes(value: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeAuthorityBlocked("evidence JSON invalid") from exc
    if not isinstance(decoded, dict):
        raise RuntimeAuthorityBlocked("evidence JSON object required")
    return decoded


def validate_activation(value: Any, *, now: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ACTIVATION_FIELDS:
        raise RuntimeAuthorityBlocked("exact activation receipt fields required")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (
        not isinstance(value["receipt_sha256"], str)
        or not HEX64.fullmatch(value["receipt_sha256"])
        or _digest_bytes(_canon(body)) != value["receipt_sha256"]
    ):
        raise RuntimeAuthorityBlocked("activation receipt digest differs")
    if (
        value["schema"] != "aionex.fr06c5e-activation-authority.v1"
        or not HEX40.fullmatch(value["source_commit"])
        or not _uuid(value["boot_id"])
        or not _uuid(value["operation_id"])
        or type(value["generation"]) is not int
        or value["generation"] < 8
        or any(
            not isinstance(value[name], str) or not HEX64.fullmatch(value[name])
            for name in (
                "full_host_closure_receipt_sha256",
                "host_state_receipt_sha256",
                "preflight_sha256",
                "boot_graph_sha256",
            )
        )
        or value["maintenance_closed"] is not True
        or value["full_host_closure"] is not True
        or value["production_activation_authorized"] is not True
    ):
        raise RuntimeAuthorityBlocked("activation authority claims invalid")
    issued, expires = value["issued_at_epoch"], value["expires_at_epoch"]
    if (
        type(now) is not int
        or type(issued) is not int
        or type(expires) is not int
        or issued <= 0
        or not 60 <= expires - issued <= 900
        or now < issued
        or now >= expires
    ):
        raise RuntimeAuthorityBlocked("activation authority not currently valid")
    return dict(value)


def validate_maintenance(value: Any, activation: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MAINTENANCE_FIELDS:
        raise RuntimeAuthorityBlocked("exact maintenance snapshot required")
    if (
        value["operation_id"] != activation["operation_id"]
        or value["generation"] != activation["generation"]
        or value["status"] != "closed"
        or value["enabled"] is not False
        or value["full_host_closure"] is not False
    ):
        raise RuntimeAuthorityBlocked("maintenance authority changed or reopened")
    return dict(value)


def validate_closure(value: Any, activation: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "operation_id", "generation", "studio_process_drain_verified",
        "turn_allocation_drain_verified", "turn_credential_expiry_verified",
        "telegram_observer_graceful_stop_verified",
        "component_full_host_flags_remain_false", "full_host_closure",
        "production_activation_authorized", "receipt_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise RuntimeAuthorityBlocked("exact full-host closure receipt required")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if (
        _digest_bytes(_canon(body)) != value["receipt_sha256"]
        or value["receipt_sha256"] != activation["full_host_closure_receipt_sha256"]
        or value["schema"] != "aionex.fr06-full-host-closure.v1"
        or value["operation_id"] != activation["operation_id"]
        or value["generation"] != activation["generation"]
        or value["full_host_closure"] is not True
        or value["production_activation_authorized"] is not False
        or any(
            value[name] is not True
            for name in (
                "studio_process_drain_verified",
                "turn_allocation_drain_verified",
                "turn_credential_expiry_verified",
                "telegram_observer_graceful_stop_verified",
                "component_full_host_flags_remain_false",
            )
        )
    ):
        raise RuntimeAuthorityBlocked(
            "full-host closure receipt differs or incomplete"
        )
    return dict(value)


def bind(
    *,
    activation: dict[str, Any],
    closure: dict[str, Any],
    maintenance: dict[str, Any],
    current_source_commit: str,
    current_boot_id: str,
    host_state_bytes: bytes,
    preflight_bytes: bytes,
    boot_graph_bytes: bytes,
    now: int | None = None,
) -> BoundContext:
    stamp = int(time.time()) if now is None else now
    accepted = validate_activation(activation, now=stamp)
    validate_maintenance(maintenance, accepted)
    validate_closure(closure, accepted)
    if (
        current_source_commit != accepted["source_commit"]
        or current_boot_id != accepted["boot_id"]
    ):
        raise RuntimeAuthorityBlocked("source commit or boot identity changed")
    for content, key in (
        (host_state_bytes, "host_state_receipt_sha256"),
        (preflight_bytes, "preflight_sha256"),
        (boot_graph_bytes, "boot_graph_sha256"),
    ):
        if not isinstance(content, bytes) or not content:
            raise RuntimeAuthorityBlocked("prerequisite evidence bytes required")
        if _digest_bytes(content) != accepted[key]:
            raise RuntimeAuthorityBlocked("prerequisite evidence digest differs")
    return BoundContext(
        source_commit=accepted["source_commit"],
        boot_id=accepted["boot_id"],
        maintenance_operation=accepted["operation_id"],
        maintenance_generation=accepted["generation"],
        host_state_receipt_sha256=accepted["host_state_receipt_sha256"],
        preflight_sha256=accepted["preflight_sha256"],
        boot_graph_sha256=accepted["boot_graph_sha256"],
        maintenance_closed=True,
    )


def bind_files(
    *,
    activation_path: Path,
    closure_path: Path,
    host_state_path: Path,
    preflight_path: Path,
    boot_graph_path: Path,
    maintenance: dict[str, Any],
    current_source_commit: str,
    current_boot_id: str,
    now: int | None = None,
) -> BoundContext:
    return bind(
        activation=_json_bytes(_file(activation_path)),
        closure=_json_bytes(_file(closure_path)),
        maintenance=maintenance,
        current_source_commit=current_source_commit,
        current_boot_id=current_boot_id,
        host_state_bytes=_file(host_state_path),
        preflight_bytes=_file(preflight_path),
        boot_graph_bytes=_file(boot_graph_path),
        now=now,
    )
