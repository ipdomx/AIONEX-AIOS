#!/usr/bin/env python3
"""Read-only Docker runtime watcher for AIONEX Production.

The watcher runs on the host under systemd. It never exposes the Docker socket to
application containers. A component must be bad on two consecutive polls before a
down alert is emitted; restart-count increases are emitted immediately.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

STATE_VERSION = 1
_SAFE_PROJECT = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_NOTIFIER_SERVICES = ("operations-observer", "communication-worker", "backend")


def _run(args: list[str]) -> str:
    result = subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    return result.stdout


def _inspect(container_id: str) -> dict[str, Any]:
    payload = json.loads(_run(["docker", "inspect", container_id]))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError("docker inspect returned an invalid payload")
    return payload[0]


def collect(project: str) -> dict[str, dict[str, Any]]:
    ids = [
        line.strip()
        for line in _run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        ).splitlines()
        if line.strip()
    ]
    components: dict[str, dict[str, Any]] = {}
    for container_id in ids:
        item = _inspect(container_id)
        config = item.get("Config") or {}
        labels = config.get("Labels") or {}
        if str(labels.get("com.docker.compose.oneoff", "False")).lower() == "true":
            continue
        service = str(labels.get("com.docker.compose.service") or "").strip()
        if not service:
            continue
        number = str(labels.get("com.docker.compose.container-number") or "1").strip()
        key = f"{service}:{number}"
        state = item.get("State") or {}
        status = str(state.get("Status") or "unknown").lower()
        health = str((state.get("Health") or {}).get("Status") or "").lower()
        healthy = status == "running" and health in {"", "healthy"}
        components[key] = {
            "service": service,
            "number": number,
            "container_id": str(item.get("Id") or container_id),
            "restart_count": max(0, int(item.get("RestartCount") or 0)),
            "status": status,
            "health": health or None,
            "healthy": healthy,
        }
    return components


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": STATE_VERSION, "components": {}}
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        return {"version": STATE_VERSION, "components": {}}
    if not isinstance(payload.get("components"), dict):
        payload["components"] = {}
    return payload


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _notifier_container(project: str) -> str | None:
    for service in _NOTIFIER_SERVICES:
        ids = [
            line.strip()
            for line in _run(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--filter",
                    f"label=com.docker.compose.service={service}",
                ]
            ).splitlines()
            if line.strip()
        ]
        if ids:
            return ids[0]
    return None


def notify(
    *,
    project: str,
    event: str,
    service: str,
    transition: int,
    restart_count: int,
) -> bool:
    container_id = _notifier_container(project)
    if not container_id:
        return False
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "1000:1000",
            container_id,
            "python",
            "-m",
            "app.services.runtime_host_alert",
            "--event",
            event,
            "--service",
            service,
            "--transition",
            str(transition),
            "--restart-count",
            str(restart_count),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def reconcile(
    previous: dict[str, Any], current: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure state transition planner used by unit tests and the live watcher."""
    old = dict(previous.get("components") or {})
    next_components: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    keys = sorted(set(old) | set(current))

    for key in keys:
        prior = dict(old.get(key) or {})
        now = current.get(key)
        if not prior:
            if now is None:
                continue
            next_components[key] = {
                **now,
                "expected": bool(now["healthy"]),
                "bad_streak": 0,
                "alerted_bad": False,
                "transition": 0,
            }
            continue

        expected = bool(prior.get("expected"))
        transition = max(0, int(prior.get("transition", 0) or 0))
        alerted_bad = bool(prior.get("alerted_bad"))
        bad_streak = max(0, int(prior.get("bad_streak", 0) or 0))

        if now is None:
            bad_streak += 1 if expected else 0
            row = {**prior, "bad_streak": bad_streak}
            if expected and bad_streak >= 2 and not alerted_bad:
                transition += 1
                row.update({"alerted_bad": True, "transition": transition})
                events.append(
                    {
                        "event": "missing",
                        "service": key,
                        "transition": transition,
                        "restart_count": int(prior.get("restart_count", 0) or 0),
                        "key": key,
                    }
                )
            next_components[key] = row
            continue

        # A newly activated profile/service becomes expected once it is healthy.
        if not expected and now["healthy"]:
            expected = True

        same_container = str(prior.get("container_id")) == str(now["container_id"])
        previous_restart = max(0, int(prior.get("restart_count", 0) or 0))
        current_restart = max(0, int(now.get("restart_count", 0) or 0))
        if expected and same_container and current_restart > previous_restart:
            transition += 1
            events.append(
                {
                    "event": "restart",
                    "service": key,
                    "transition": transition,
                    "restart_count": current_restart,
                    "key": key,
                }
            )

        if expected and not now["healthy"]:
            bad_streak += 1
            if bad_streak >= 2 and not alerted_bad:
                transition += 1
                alerted_bad = True
                events.append(
                    {
                        "event": "unhealthy",
                        "service": key,
                        "transition": transition,
                        "restart_count": current_restart,
                        "key": key,
                    }
                )
        else:
            bad_streak = 0
            if expected and alerted_bad and now["healthy"]:
                transition += 1
                events.append(
                    {
                        "event": "recovered",
                        "service": key,
                        "transition": transition,
                        "restart_count": current_restart,
                        "key": key,
                    }
                )
                alerted_bad = False

        next_components[key] = {
            **now,
            "expected": expected,
            "bad_streak": bad_streak,
            "alerted_bad": alerted_bad,
            "transition": transition,
        }

    return {"version": STATE_VERSION, "components": next_components}, events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="web-dashboard")
    parser.add_argument(
        "--state-file", default="/var/lib/aionex-runtime-watch/state.json"
    )
    args = parser.parse_args()
    if not _SAFE_PROJECT.fullmatch(args.project):
        raise SystemExit("invalid compose project")

    state_path = Path(args.state_file)
    previous = _load_state(state_path)
    current = collect(args.project)
    planned, events = reconcile(previous, current)

    # Persist only events that were successfully sent. Failed notifications remain
    # pending by rolling their transition markers back to the previous state.
    failed_keys: set[str] = set()
    for event in events:
        if not notify(
            project=args.project,
            event=event["event"],
            service=event["service"],
            transition=int(event["transition"]),
            restart_count=int(event["restart_count"]),
        ):
            failed_keys.add(str(event["key"]))

    if failed_keys:
        prior_components = previous.get("components") or {}
        for key in failed_keys:
            if key in prior_components:
                planned["components"][key] = prior_components[key]
    _write_state(state_path, planned)
    return 1 if failed_keys else 0


if __name__ == "__main__":
    raise SystemExit(main())
