#!/usr/bin/env python3
"""Private, read-only Coturn measurement; NOT a maintenance/rollout authorization.

The caller supplies the complete expected container set. Docker labels, the
pinned image, PID start time, boot ID, network namespace and daemon-owned
loopback listener are checked before and after two fresh bounded scrapes.
Only aggregate allocation counts leave the network namespace. No credentials,
raw metrics, process command lines or configuration contents are returned.

Run only during a separately authorized observation step. This program does not
enable metrics, open ports, stop/restart containers, change admission, settle
ownership, or certify full-host drain. Missing series mean UNKNOWN, never zero.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from uuid import UUID

COTURN_IMAGE = "sha256:75e9ebd1e19005bec0c7f591d29afe22f959916ac8d9c852452f27db8c789828"
METRIC = "turn_total_allocations"
METRICS_PORT = 9641
MAX_BYTES = 1024 * 1024
MAX_INSTANCES = 4
_ID = re.compile(r"[0-9a-f]{64}\Z")
_SAMPLE = re.compile(r'turn_total_allocations\{type="(UDP|TCP)"\} ([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\Z')
_DECLARATION = re.compile(r"# TYPE turn_total_allocations gauge\Z")


class TurnObservationUnavailable(RuntimeError):
    """A fixed, non-sensitive reason for refusing an observation."""


@dataclass(frozen=True, slots=True)
class AllocationCounts:
    values: tuple[tuple[str, int], ...]

    @property
    def total(self) -> int:
        return sum(count for _, count in self.values)


def parse_allocation_counts(payload: bytes, required_types: tuple[str, ...]) -> AllocationCounts:
    """Parse the pinned exporter's exact gauge contract without label leakage."""
    if (
        not required_types or len(set(required_types)) != len(required_types)
        or not set(required_types) <= {"UDP", "TCP"}
    ):
        raise TurnObservationUnavailable("invalid_required_transport_set")
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BYTES:
        raise TurnObservationUnavailable("invalid_metrics_size")
    if not payload.endswith(b"\n"):
        raise TurnObservationUnavailable("truncated_metrics")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError:
        raise TurnObservationUnavailable("invalid_metrics_encoding") from None
    if "\x00" in text or "\r" in text:
        raise TurnObservationUnavailable("invalid_metrics_control_character")
    declared = False
    values: dict[str, int] = {}
    for line in text.splitlines():
        if len(line) > 16384:
            raise TurnObservationUnavailable("metrics_line_too_large")
        if line.startswith("# TYPE " + METRIC):
            if declared or not _DECLARATION.fullmatch(line):
                raise TurnObservationUnavailable("invalid_allocation_metric_type")
            declared = True
        elif line.startswith(METRIC):
            match = _SAMPLE.fullmatch(line)
            if match is None or not declared:
                raise TurnObservationUnavailable("malformed_allocation_sample")
            kind, raw = match.groups()
            if kind in values:
                raise TurnObservationUnavailable("duplicate_allocation_series")
            try:
                value = Decimal(raw)
                valid = value.is_finite() and 0 <= value <= 2**53 - 1 and value == value.to_integral_value()
            except (InvalidOperation, ValueError):
                valid = False
            if not valid:
                raise TurnObservationUnavailable("invalid_allocation_count")
            values[kind] = int(value)
    if not declared or not values:
        raise TurnObservationUnavailable("allocation_metric_missing")
    if not set(required_types) <= set(values):
        raise TurnObservationUnavailable("allocation_transport_missing")
    # Unexpected transport contradicts the explicit runtime relay profile.
    if set(values) != set(required_types):
        raise TurnObservationUnavailable("allocation_transport_profile_mismatch")
    return AllocationCounts(tuple(sorted(values.items())))


@dataclass(frozen=True, slots=True)
class CoturnEpoch:
    container_id: str
    image_id: str
    host_pid: int
    process_start_ticks: int
    boot_id: str
    network_namespace_inode: int
    listener_socket_inode: int
    restart_count: int
    started_at: str
    relay_types: tuple[str, ...]


class TurnReader(Protocol):
    def instances(self) -> tuple[str, ...]: ...
    def epoch(self, container_id: str) -> CoturnEpoch: ...
    def scrape(self, epoch: CoturnEpoch) -> AllocationCounts: ...


@dataclass(frozen=True, slots=True)
class PrivateTurnObservation:
    epochs: tuple[CoturnEpoch, ...]
    first: tuple[AllocationCounts, ...]
    second: tuple[AllocationCounts, ...]
    observed_at: str
    elapsed_seconds: float
    all_observed_counts_zero: bool
    scope: str = "exact_coturn_instances_two_point_observation_only"
    maintenance_authority_verified: bool = False
    credential_admission_closed_verified: bool = False
    turn_allocation_drain_verified: bool = False
    provider_drain_verified: bool = False
    full_host_closure: bool = False
    migration_0064_rollout_allowed: bool = False


def observe_private_turn(
    reader: TurnReader, expected_ids: tuple[str, ...], *, deadline_seconds: float = 30.0,
) -> PrivateTurnObservation:
    """Refuse incomplete, restarted or changed fleets, including ABA process changes."""
    if (
        not expected_ids or len(expected_ids) > MAX_INSTANCES
        or len(set(expected_ids)) != len(expected_ids)
        or any(not _ID.fullmatch(item) for item in expected_ids)
        or not 0 < deadline_seconds <= 30
    ):
        raise TurnObservationUnavailable("invalid_expected_instance_set")
    expected = tuple(sorted(expected_ids))
    started = time.monotonic()

    def check_deadline() -> None:
        if time.monotonic() - started > deadline_seconds:
            raise TurnObservationUnavailable("observation_deadline_exceeded")

    def check_fleet() -> None:
        check_deadline()
        if tuple(sorted(reader.instances())) != expected:
            raise TurnObservationUnavailable("coturn_instance_set_changed_or_incomplete")

    check_fleet()
    epochs = tuple(reader.epoch(cid) for cid in expected)
    if tuple(item.container_id for item in epochs) != expected:
        raise TurnObservationUnavailable("coturn_epoch_identity_mismatch")
    if len({item.network_namespace_inode for item in epochs}) != len(epochs):
        raise TurnObservationUnavailable("shared_coturn_network_namespace")
    first: list[AllocationCounts] = []
    second: list[AllocationCounts] = []
    for samples in (first, second):
        for epoch in epochs:
            check_deadline()
            if reader.epoch(epoch.container_id) != epoch:
                raise TurnObservationUnavailable("coturn_process_epoch_changed")
            sample = reader.scrape(epoch)
            if (
                not isinstance(sample, AllocationCounts)
                or tuple(kind for kind, _ in sample.values) != tuple(sorted(epoch.relay_types))
                or any(type(count) is not int or not 0 <= count <= 2**53 - 1 for _, count in sample.values)
            ):
                raise TurnObservationUnavailable("invalid_private_allocation_counts")
            samples.append(sample)
            if reader.epoch(epoch.container_id) != epoch:
                raise TurnObservationUnavailable("coturn_process_epoch_changed")
        check_fleet()
    if tuple(reader.epoch(cid) for cid in expected) != epochs:
        raise TurnObservationUnavailable("coturn_process_epoch_changed")
    check_deadline()
    return PrivateTurnObservation(
        epochs=epochs, first=tuple(first), second=tuple(second),
        observed_at=datetime.now(UTC).isoformat(),
        elapsed_seconds=time.monotonic() - started,
        all_observed_counts_zero=all(item.total == 0 for item in (*first, *second)),
    )


def _read_bounded(path: Path, maximum: int = MAX_BYTES) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise TurnObservationUnavailable("proc_observation_too_large")
    return data


def _loopback_listener(proc: Path) -> int:
    """The one metrics listener must belong to the actual turnserver process."""
    listeners: list[tuple[str, int]] = []
    for name in ("tcp", "tcp6"):
        for line in _read_bounded(proc / "net" / name).decode("ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10:
                raise TurnObservationUnavailable("malformed_proc_socket_table")
            address, port = fields[1].split(":")
            if fields[3] == "0A" and int(port, 16) == METRICS_PORT:
                listeners.append((address, int(fields[9])))
    if len(listeners) != 1 or listeners[0][0] != "0100007F":
        raise TurnObservationUnavailable("metrics_listener_not_private_or_missing")
    inode = listeners[0][1]
    if inode <= 0:
        raise TurnObservationUnavailable("invalid_listener_inode")
    links = list((proc / "fd").iterdir())
    if len(links) > 65536:
        raise TurnObservationUnavailable("too_many_daemon_file_descriptors")
    found = False
    for link in links:
        try:
            found |= os.readlink(link) == f"socket:[{inode}]"
        except FileNotFoundError:
            # An unrelated short-lived FD can vanish; the target must still match.
            continue
    if not found:
        raise TurnObservationUnavailable("metrics_listener_not_owned_by_coturn")
    return inode


_INSPECT = '''{{ $u := false }}{{ $t := false }}{{ range .Args }}{{ if eq . "--no-tcp-relay" }}{{ $u = true }}{{ end }}{{ if eq . "--no-udp-relay" }}{{ $t = true }}{{ end }}{{ end }}{"id":{{json .Id}},"image":{{json .Image}},"pid":{{.State.Pid}},"running":{{.State.Running}},"paused":{{.State.Paused}},"restarting":{{.State.Restarting}},"restarts":{{.RestartCount}},"started_at":{{json .State.StartedAt}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"network_mode":{{json .HostConfig.NetworkMode}},"ports":{{json .HostConfig.PortBindings}},"entrypoint":{{json .Config.Entrypoint}},"udp_only_flag":{{$u}},"tcp_only_flag":{{$t}}}'''


class DockerCoturnReader:
    """Root host reader with fixed image/port/service and no raw configuration read."""

    def __init__(self, project: str = "web-dashboard") -> None:
        if project != "web-dashboard" and not re.fullmatch(r"aionex-turn-observer-lab-[0-9a-f]{12}", project):
            raise TurnObservationUnavailable("unexpected_compose_project")
        self.project = project

    @staticmethod
    def _run(arguments: list[str], *, pass_fds: tuple[int, ...] = (), allow_unknown: bool = False) -> str:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=5, check=False, pass_fds=pass_fds)
        except (OSError, subprocess.TimeoutExpired):
            raise TurnObservationUnavailable("private_reader_command_unavailable") from None
        if result.returncode not in ((0, 2) if allow_unknown else (0,)) or len(result.stdout) > 65536:
            raise TurnObservationUnavailable("private_reader_command_failed")
        return result.stdout

    def instances(self) -> tuple[str, ...]:
        output = self._run([
            "docker", "container", "ls", "--all", "--quiet", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={self.project}",
            "--filter", "label=com.docker.compose.service=realtime-turn",
        ])
        ids = tuple(output.split())
        if any(not _ID.fullmatch(cid) for cid in ids):
            raise TurnObservationUnavailable("invalid_container_inventory")
        return tuple(sorted(ids))

    def epoch(self, container_id: str) -> CoturnEpoch:
        if os.geteuid() != 0 or not _ID.fullmatch(container_id):
            raise TurnObservationUnavailable("root_and_exact_container_identity_required")
        try:
            data = json.loads(self._run(["docker", "inspect", "--type", "container", "--format", _INSPECT, container_id]))
            if (
                data["id"] != container_id or data["image"] != COTURN_IMAGE
                or data["project"] != self.project or data["service"] != "realtime-turn"
                or data["running"] is not True or data["paused"] is not False
                or data["restarting"] is not False or type(data["pid"]) is not int or data["pid"] <= 1
                or data["entrypoint"] != ["/usr/bin/turnserver"]
                or not isinstance(data["network_mode"], str)
                or data["network_mode"] == "host" or data["network_mode"].startswith("container:")
                or (data["ports"] is not None and not isinstance(data["ports"], dict))
                or any(not isinstance(key, str) for key in (data["ports"] or {}))
                or type(data["restarts"]) is not int or data["restarts"] < 0
                or not isinstance(data["started_at"], str)
                or type(data["udp_only_flag"]) is not bool or type(data["tcp_only_flag"]) is not bool
                or any(key.split("/")[0] == str(METRICS_PORT) for key in (data["ports"] or {}))
            ):
                raise TurnObservationUnavailable("coturn_container_binding_invalid")
            if data["udp_only_flag"] and data["tcp_only_flag"]:
                raise TurnObservationUnavailable("conflicting_relay_transport_flags")
            relay_types = ("UDP",) if data["udp_only_flag"] else (("TCP",) if data["tcp_only_flag"] else ("TCP", "UDP"))
            proc = Path("/proc") / str(data["pid"])
            raw_stat = _read_bounded(proc / "stat", 8192).decode("ascii")
            head, separator, rest = raw_stat.rpartition(")")
            if not separator or head.split("(", 1)[1] != "turnserver" or Path(os.readlink(proc / "exe")).name != "turnserver":
                raise TurnObservationUnavailable("unexpected_coturn_daemon")
            ticks = int(rest.split()[19])
            namespace = (proc / "ns/net").stat().st_ino
            if ticks <= 0 or namespace == Path("/proc/self/ns/net").stat().st_ino:
                raise TurnObservationUnavailable("invalid_daemon_epoch_or_shared_host_network")
            boot = str(UUID(_read_bounded(Path("/proc/sys/kernel/random/boot_id"), 100).decode().strip()))
            return CoturnEpoch(
                container_id, data["image"], data["pid"], ticks, boot, namespace,
                _loopback_listener(proc), data["restarts"], data["started_at"], relay_types,
            )
        except (KeyError, ValueError, IndexError, TypeError, OSError):
            raise TurnObservationUnavailable("coturn_epoch_unavailable") from None

    def scrape(self, epoch: CoturnEpoch) -> AllocationCounts:
        # Hold the exact network namespace FD across exec; PID reuse cannot redirect
        # the request to another namespace. Post-scrape epoch validation is mandatory.
        try:
            fd = os.open(f"/proc/{epoch.host_pid}/ns/net", os.O_RDONLY)
            try:
                if os.fstat(fd).st_ino != epoch.network_namespace_inode:
                    raise TurnObservationUnavailable("coturn_network_epoch_changed")
                raw = self._run([
                    "nsenter", f"--net=/proc/self/fd/{fd}", "--", sys.executable, "-I",
                    str(Path(__file__).resolve()), "_scrape", ",".join(epoch.relay_types),
                ], pass_fds=(fd,), allow_unknown=True)
            finally:
                os.close(fd)
            data = json.loads(raw)
            if data.get("status") == "UNKNOWN" and data.get("reason") in {
                "allocation_metric_missing", "allocation_transport_missing",
                "allocation_transport_profile_mismatch", "malformed_allocation_sample",
                "duplicate_allocation_series", "invalid_allocation_count",
            }:
                raise TurnObservationUnavailable(data["reason"])
            if data.get("status") != "OBSERVED":
                raise TurnObservationUnavailable("allocation_metrics_unavailable")
            # Re-parse the numeric, aggregate-only child response before trusting it.
            if not isinstance(data.get("values"), list):
                raise TurnObservationUnavailable("invalid_private_reader_response")
            lines = ["# TYPE turn_total_allocations gauge"]
            for kind, count in data["values"]:
                if kind not in {"UDP", "TCP"} or type(count) is not int or count < 0:
                    raise TurnObservationUnavailable("invalid_private_reader_response")
                lines.append(f'turn_total_allocations{{type="{kind}"}} {count}')
            return parse_allocation_counts(("\n".join(lines) + "\n").encode(), epoch.relay_types)
        except (OSError, ValueError, KeyError, TypeError):
            raise TurnObservationUnavailable("private_scrape_unavailable") from None


def _scrape_loopback(required_types: tuple[str, ...]) -> AllocationCounts:
    connection = http.client.HTTPConnection("127.0.0.1", METRICS_PORT, timeout=3)
    try:
        # HTTPConnection does not use environment proxies or follow redirects.
        connection.request("GET", "/metrics", headers={"Accept": "text/plain", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
            raise TurnObservationUnavailable("invalid_metrics_http_response")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip() != "text/plain":
            raise TurnObservationUnavailable("invalid_metrics_content_type")
        return parse_allocation_counts(response.read(MAX_BYTES + 1), required_types)
    except (OSError, http.client.HTTPException):
        raise TurnObservationUnavailable("metrics_http_unavailable") from None
    finally:
        connection.close()


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "_scrape":
            counts = _scrape_loopback(tuple(sys.argv[2].split(",")))
            print(json.dumps({"status": "OBSERVED", "values": counts.values}))
            return 0
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--expected-container", action="append", required=True)
        parser.add_argument("--project", default="web-dashboard")
        args = parser.parse_args()
        result = observe_private_turn(DockerCoturnReader(args.project), tuple(args.expected_container))
        print(json.dumps({"status": "OBSERVED", **asdict(result)}, sort_keys=True))
        return 0
    except TurnObservationUnavailable as exc:
        print(json.dumps({"status": "UNKNOWN", "reason": str(exc), "turn_allocation_drain_verified": False, "migration_0064_rollout_allowed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
