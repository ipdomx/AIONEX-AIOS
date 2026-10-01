"""Pure C5D inventory/epoch verifier; NOT a production operator or authority issuer.

Inputs must be captured/loaded by a future reviewed adapter under the accepted
exclusive execution control. This module performs no I/O. Hash commitments are
checked AND raw graceful-stop records are revalidated. It does not prove CI,
file custody, Studio/Coturn closure, writer/underlay closure or permission to
change the host. It is deliberately not wired into the live cutover operator.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from scripts.security.fr06c5d11_graceful_stop_acceptance import accept

DRAINED = ("telegram-worker", "user-telegram-worker", "operations-observer")
RUNNING_SINGLETONS = (
    "academy-course-worker", "audio-dubbing-worker", "audio-music-worker",
    "audio-song-worker", "audio-speech-worker", "audio-transcript-worker",
    "backend", "backup-worker", "cloudflared", "communication-worker",
    "design-image-derivative-worker", "design-image-worker", "frontend",
    "identity-media-worker", "media-worker", "nginx", "ollama", "portal",
    "postgres", "realtime-egress", "realtime-livekit", "realtime-turn", "redis",
    "security-remediation-worker", "security-scan-worker", "security-zap",
    "studio-worker", "three-d-worker", "video-provider-worker",
)
ONESHOTS = (
    "postgres-credential-reconciler", "backup-asset-root-init",
    "security-tool-cache-init", "realtime-recording-init",
)
SCHEMA = "aionex.fr06c5d-epoch-inventory.v1"


class InventoryBlocked(ValueError):
    """Incomplete, inconsistent or stale evidence is not acceptance."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryBlocked(message)


def _hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def evidence_digest(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise InventoryBlocked("evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Binding:
    source_commit: str
    boot_id: str
    operation_id: str
    generation: int
    before_sha256: str
    after_sha256: str
    stop_receipts_sha256: str


@dataclass(frozen=True)
class ContainerEpoch:
    container_id: str
    name: str
    service: str
    image: str
    restart_count: int
    restart_policy: str
    maximum_retry_count: int
    desired_state: str


@dataclass(frozen=True)
class VerifiedInventory:
    binding: Binding
    observed_at: str
    containers: tuple[ContainerEpoch, ...]
    oneshots: tuple[ContainerEpoch, ...]
    # This class is never usable as full-host closure or activation authority.
    full_host_closure: bool = False
    production_activation_authorized: bool = False

    @property
    def running_ids(self) -> tuple[str, ...]:
        return tuple(r.container_id for r in self.containers if r.desired_state == "running")

    @property
    def drained_ids(self) -> tuple[str, ...]:
        return tuple(r.container_id for r in self.containers if r.desired_state == "drained")


def _policy(row: dict[str, Any]) -> tuple[str, int]:
    host = row.get("HostConfig")
    _need(isinstance(host, dict), "host configuration unavailable")
    policy = host.get("RestartPolicy")
    _need(isinstance(policy, dict), "restart policy record unavailable")
    name, retries = policy.get("Name"), policy.get("MaximumRetryCount")
    _need(name in ("no", "always", "unless-stopped", "on-failure"), "invalid restart policy")
    _need(type(retries) is int and retries >= 0, "invalid restart retry count")
    _need(name == "on-failure" or retries == 0, "unexpected restart retry count")
    return name, retries


def _stopped(state: dict[str, Any]) -> None:
    _need(state.get("Status") == "exited" and state.get("Running") is False,
          "stopped state is not explicit")
    _need(type(state.get("ExitCode")) is int and state["ExitCode"] == 0,
          "stopped exit code is not exact integer zero")


def verify(*, observation: dict[str, Any], before: dict[str, Any],
           after: dict[str, Any], stop_receipts: dict[str, Any], binding: Binding,
           now: datetime, max_age_seconds: int = 120) -> VerifiedInventory:
    """Validate the fixed 40-container profile, returning no execution authority.

    `all_container_ids` must come from an UNFILTERED whole-host Docker inventory;
    its capture provenance is a caller obligation, not inferable from a flag.
    `now` must be the real UTC clock in the production adapter; tests use a
    clearly synthetic clock. Before/after digests alone never accept a stop.
    """
    _need(isinstance(binding, Binding), "typed binding required")
    _need(_hex(binding.source_commit, 40) and _uuid(binding.boot_id)
          and _uuid(binding.operation_id), "invalid source/boot/operation binding")
    _need(type(binding.generation) is int and binding.generation >= 8, "invalid generation")
    _need(type(max_age_seconds) is int and 1 <= max_age_seconds <= 300, "invalid freshness bound")
    _need(isinstance(now, datetime) and now.utcoffset() == timedelta(0), "actual UTC clock required")
    _need(isinstance(observation, dict) and set(observation) == {
        "schema", "source_commit", "boot_id", "observed_at", "authority",
        "all_container_ids", "containers"}, "exact observation fields required")
    _need(observation["schema"] == SCHEMA and observation["source_commit"] == binding.source_commit
          and observation["boot_id"] == binding.boot_id, "source or boot drift")
    stamp = observation["observed_at"]
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
    except ValueError as exc:
        raise InventoryBlocked("invalid observation timestamp") from exc
    _need(observed is not None and observed.utcoffset() == timedelta(0), "observation must be UTC")
    _need(0 <= (now - observed).total_seconds() <= max_age_seconds, "stale or future observation")
    authority = {"schema_version": 8, "operation_id": binding.operation_id,
                 "generation": binding.generation, "status": "closed", "enabled": False,
                 "full_host_closure": False}
    actual = observation["authority"]
    _need(isinstance(actual, dict) and actual == authority and type(actual.get("schema_version")) is int
          and type(actual.get("generation")) is int and actual.get("enabled") is False
          and actual.get("full_host_closure") is False, "current closed authority mismatch")
    projection = {k: v for k, v in authority.items() if k != "schema_version"}
    for raw, expected in ((before, binding.before_sha256), (after, binding.after_sha256),
                          (stop_receipts, binding.stop_receipts_sha256)):
        _need(_hex(expected, 64) and evidence_digest(raw) == expected, "receipt commitment mismatch")
    _need(isinstance(before, dict) and isinstance(after, dict) and isinstance(stop_receipts, dict),
          "raw graceful evidence required")
    _need(before.get("authority") == projection and after.get("authority") == projection,
          "graceful evidence authority mismatch")
    _need(set(stop_receipts) == set(DRAINED), "exact stop receipt set required")
    try:
        graceful = accept(before=before, after=after)
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InventoryBlocked("raw graceful-stop evidence rejected") from exc
    _need(graceful.operation_id == binding.operation_id and graceful.generation == binding.generation,
          "graceful proof binding mismatch")

    ids, rows = observation["all_container_ids"], observation["containers"]
    _need(isinstance(ids, list) and len(ids) == 40 and all(_hex(i, 64) for i in ids)
          and len(set(ids)) == 40, "exact whole-host inventory required")
    _need(isinstance(rows, list) and len(rows) == 40 and all(isinstance(r, dict) for r in rows),
          "exact inspection row set required")
    inspected_ids = [r.get("Id") for r in rows]
    _need(all(_hex(i, 64) for i in inspected_ids) and len(set(inspected_ids)) == 40
          and set(inspected_ids) == set(ids), "inspection/list identity mismatch")
    expected_names = {f"web-dashboard-{s}-1": s for s in (*RUNNING_SINGLETONS, *DRAINED, *ONESHOTS)}
    expected_names.update({f"web-dashboard-project-worker-{i}": "project-worker" for i in range(1, 5)})
    names: set[str] = set()
    result: list[ContainerEpoch] = []
    oneshots: list[ContainerEpoch] = []
    for row in rows:
        name = row.get("Name")
        _need(isinstance(name, str) and name.startswith("/") and name[1:] in expected_names,
              "unexpected container name")
        name = name[1:]
        _need(name not in names, "duplicate container name")
        names.add(name)
        config, state = row.get("Config"), row.get("State")
        _need(isinstance(config, dict) and isinstance(state, dict), "container state unavailable")
        labels = config.get("Labels")
        _need(isinstance(labels, dict) and labels.get("com.docker.compose.project") == "web-dashboard"
              and labels.get("com.docker.compose.service") == expected_names[name]
              and str(labels.get("com.docker.compose.oneoff", "False")).lower() == "false",
              "container service identity mismatch")
        service = expected_names[name]
        image, restarts = row.get("Image"), row.get("RestartCount")
        _need(isinstance(image, str) and image.startswith("sha256:") and _hex(image[7:], 64),
              "exact image identity required")
        _need(type(restarts) is int and restarts >= 0, "restart epoch unavailable")
        _need(all(state.get(k) is False for k in ("Paused", "Restarting", "Dead", "OOMKilled")),
              "unstable or incomplete container state")
        policy, retries = _policy(row)
        if service in DRAINED:
            _stopped(state)
            _need(policy == "no" and retries == 0, "drained restart policy must remain no")
            receipt = stop_receipts[service]
            _need(isinstance(receipt, dict), "stop receipt missing")
            expected = {"operation_id": binding.operation_id, "generation": binding.generation,
                        "service": service, "container_id": row["Id"], "image": image,
                        "restart_count": restarts, "signal": "SIGTERM", "exit_code": 0,
                        "forced_kill": False, "replayed_signal": False}
            _need(all(receipt.get(k) == v for k, v in expected.items()), "stop receipt epoch mismatch")
            _need(type(receipt.get("generation")) is int and type(receipt.get("restart_count")) is int
                  and type(receipt.get("exit_code")) is int and receipt.get("forced_kill") is False
                  and receipt.get("replayed_signal") is False, "stop receipt types or provenance invalid")
            for raw in (before, after):
                epoch = raw["services"][service]
                _need(epoch.get("container_id") == row["Id"] and type(epoch.get("restart_count")) is int
                      and epoch["restart_count"] == restarts, "drained container epoch changed")
            _need(type(after["services"][service].get("exit_code")) is int, "exit proof must be integer")
            desired = "drained"
        elif service in ONESHOTS:
            _stopped(state)
            _need(policy == "no" and retries == 0, "oneshot restart policy mismatch")
            desired = "oneshot"
        else:
            _need(state.get("Running") is True and state.get("Status") == "running", "required service not running")
            healthcheck = config.get("Healthcheck", {})
            _need(isinstance(healthcheck, dict), "healthcheck record invalid")
            check = healthcheck.get("Test", [])
            _need(isinstance(check, list) and all(isinstance(x, str) for x in check),
                  "healthcheck command invalid")
            _need(not check or check[0] in ("CMD", "CMD-SHELL", "NONE"), "unknown healthcheck mode")
            _need(not check or (check[0] == "NONE" and len(check) == 1)
                  or (check[0] != "NONE" and len(check) >= 2), "healthcheck command incomplete")
            enabled = bool(check) and check[0] != "NONE"
            _need(enabled or service == "cloudflared", "required healthcheck missing")
            health = state.get("Health", {})
            _need(isinstance(health, dict), "health observation invalid")
            _need(not enabled or health.get("Status") == "healthy", "running health not ready")
            desired = "running"
        epoch = ContainerEpoch(row["Id"], name, service, image, restarts, policy, retries, desired)
        (oneshots if desired == "oneshot" else result).append(epoch)
    _need(names == set(expected_names), "service topology incomplete")
    return VerifiedInventory(binding, stamp, tuple(sorted(result, key=lambda r: r.name)),
                             tuple(sorted(oneshots, key=lambda r: r.name)))
