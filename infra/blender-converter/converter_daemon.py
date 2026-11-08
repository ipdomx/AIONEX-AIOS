"""AIONEX headless Blender conversion sidecar (roadmap 2.4).

Runs in the ``three-d-converter`` container, which has no network
(``network_mode: none``), a read-only root filesystem, no capabilities and a
non-root user. The three-d-worker hands it work through a shared spool volume:

    <spool>/requests/<id>/   written by the worker, then atomically renamed in
        input.glb            the untrusted model (already structurally validated)
        request.json         {"input_format": "glb", "formats": [...], "thumbnail": bool}
    <spool>/work/<id>/       claimed by this daemon (atomic rename)
    <spool>/done/<id>/       finished: result.json plus out/ files
    <spool>/status.json      heartbeat: Blender version, formats, timestamp

Each request runs Blender once as a child process with a wall-clock timeout
that kills the process group, POSIX resource limits, a scrubbed environment,
private HOME/config/script directories, ``--factory-startup``,
``--disable-autoexec`` and ``--offline-mode``. Standard library only; it runs on
the image's system Python, never on Blender's bundled Python.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Callable

SPOOL = Path(os.environ.get("AIONEX_CONVERTER_SPOOL", "/var/lib/aionex/three-d-conversion"))
BLENDER = os.environ.get("AIONEX_BLENDER_BINARY", "/opt/blender/blender")
SCRIPT = Path(os.environ.get("AIONEX_BLENDER_SCRIPT", "/opt/aionex/three_d_convert.py"))
REQUIRED_SERIES = os.environ.get("AIONEX_BLENDER_SERIES", "5.2")
TIMEOUT_SECONDS = int(os.environ.get("AIONEX_CONVERTER_TIMEOUT_SECONDS", "110"))
MEMORY_BYTES = int(os.environ.get("AIONEX_CONVERTER_MEMORY_BYTES", str(6 * 1024**3)))
CPU_SECONDS = int(os.environ.get("AIONEX_CONVERTER_CPU_SECONDS", "240"))
MAX_OUTPUT_BYTES = int(os.environ.get("AIONEX_CONVERTER_MAX_OUTPUT_BYTES", str(200 * 1024**2)))
MAX_INPUT_BYTES = int(os.environ.get("AIONEX_CONVERTER_MAX_INPUT_BYTES", str(100 * 1024**2)))
THUMBNAIL_SIZE = int(os.environ.get("AIONEX_CONVERTER_THUMBNAIL_SIZE", "512"))
STALE_SECONDS = int(os.environ.get("AIONEX_CONVERTER_STALE_SECONDS", "900"))
STATUS_MAX_AGE_SECONDS = 60
FORMATS = ("obj", "fbx", "usdz")
_ID = re.compile(r"[0-9a-f]{32}")
_VERSION = re.compile(r"Blender\s+(\d+\.\d+\.\d+)(?:\s+LTS)?")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def resource_limits() -> dict[int, int]:
    return {
        resource.RLIMIT_AS: MEMORY_BYTES,
        resource.RLIMIT_CPU: CPU_SECONDS,
        resource.RLIMIT_FSIZE: MAX_OUTPUT_BYTES,
        resource.RLIMIT_NOFILE: 512,
        resource.RLIMIT_CORE: 0,
    }


def _apply_limits() -> None:
    # The daemon is single-threaded, so a preexec hook is safe here.
    for name, value in resource_limits().items():
        resource.setrlimit(name, (value, value))
    os.umask(0o077)


def sandbox_env(home: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in ("LANG", "LC_ALL", "TZ") if key in os.environ}
    for name in ("config", "scripts", "extensions", "datafiles", "tmp"):
        (home / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(home / "tmp"),
            "NO_COLOR": "1",
            "PATH": "/usr/bin:/bin",
            "BLENDER_USER_CONFIG": str(home / "config"),
            "BLENDER_USER_SCRIPTS": str(home / "scripts"),
            "BLENDER_USER_EXTENSIONS": str(home / "extensions"),
            "BLENDER_USER_DATAFILES": str(home / "datafiles"),
        }
    )
    return env


def run_sandboxed(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        preexec_fn=_apply_limits,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return subprocess.CompletedProcess(command, -signal.SIGKILL, "timeout", "")
    return subprocess.CompletedProcess(command, process.returncode, stdout, "")


def blender_command(*args: str) -> list[str]:
    return [BLENDER, "--background", "--factory-startup", "--disable-autoexec", "--offline-mode", *args]


def probe(runner: Runner = run_sandboxed, *, scratch: Path | None = None) -> dict[str, Any]:
    root = scratch or (SPOOL / "probe")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(mode=0o700, parents=True)
    try:
        result = runner([BLENDER, "--factory-startup", "--version"], cwd=root, env=sandbox_env(root / "home"), timeout=30)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    lines = (result.stdout or "").strip().splitlines()
    match = _VERSION.fullmatch(lines[0].strip()) if result.returncode == 0 and lines else None
    version = match.group(1) if match else None
    ready = bool(version) and (version == REQUIRED_SERIES or str(version).startswith(REQUIRED_SERIES + "."))
    return {
        "available": ready,
        "blender_version": version,
        "formats": list(FORMATS) if ready else [],
        "thumbnail": ready,
        "updated_at": time.time(),
        "reason": "ready" if ready else ("blender_version_not_pinned" if version else "blender_probe_failed"),
    }


def write_status(status: dict[str, Any]) -> None:
    tmp = SPOOL / ".status.json.tmp"
    tmp.write_text(json.dumps(status), encoding="utf-8")
    os.chmod(tmp, 0o640)
    os.replace(tmp, SPOOL / "status.json")


def _fail(reason: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason, "results": {}}


def process_request(job: Path, runner: Runner = run_sandboxed) -> dict[str, Any]:
    request_path = job / "request.json"
    source = job / "input.glb"
    if not request_path.is_file() or request_path.is_symlink() or not source.is_file() or source.is_symlink():
        return _fail("request_incomplete")
    if source.stat().st_size > MAX_INPUT_BYTES:
        return _fail("input_too_large")
    with source.open("rb") as handle:
        if handle.read(4) != b"glTF":
            return _fail("input_not_glb")
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail("request_invalid")
    if not isinstance(request, dict) or request.get("input_format") != "glb":
        return _fail("request_invalid")
    formats = [fmt for fmt in request.get("formats") or [] if fmt in FORMATS]
    thumbnail = bool(request.get("thumbnail"))
    try:
        thumbnail_size = max(64, min(2048, int(request.get("thumbnail_size") or THUMBNAIL_SIZE)))
    except (TypeError, ValueError):
        return _fail("request_invalid")
    out = job / "out"
    out.mkdir(mode=0o700, exist_ok=True)
    spec = {
        "input": str(source),
        "input_format": "glb",
        "outputs": [{"format": fmt, "path": str(out / fmt / ("model." + fmt))} for fmt in formats],
        "thumbnail": {"path": str(out / "preview.png"), "size": thumbnail_size} if thumbnail else None,
        "result": str(job / "blender-result.json"),
    }
    spec_path = job / "blender-spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    home = job / "home"
    started = time.monotonic()
    completed = runner(
        blender_command("--python-exit-code", "1", "--python", str(SCRIPT), "--", str(spec_path)),
        cwd=job,
        env=sandbox_env(home),
        timeout=TIMEOUT_SECONDS,
    )
    shutil.rmtree(home, ignore_errors=True)
    seconds = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        reason = "timeout" if completed.stdout == "timeout" else "blender_exit_nonzero"
        return {"ok": False, "reason": reason, "results": {}, "seconds": seconds}
    try:
        report = json.loads((job / "blender-result.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "reason": "blender_result_missing", "results": {}, "seconds": seconds}
    results = report.get("results") if isinstance(report, dict) else None
    return {
        "ok": True,
        "reason": "converted",
        "blender_version": report.get("blender") if isinstance(report, dict) else None,
        "results": results if isinstance(results, dict) else {},
        "seconds": seconds,
    }


def _finish(job: Path, result: dict[str, Any]) -> None:
    (job / "result.json").write_text(json.dumps(result), encoding="utf-8")
    for leftover in ("input.glb", "blender-spec.json", "blender-result.json"):
        with contextlib.suppress(FileNotFoundError):
            (job / leftover).unlink()
    os.replace(job, SPOOL / "done" / job.name)


def collect_stale(now: float | None = None) -> int:
    moment = time.time() if now is None else now
    removed = 0
    for bucket in ("done", "requests", "work"):
        for entry in (SPOOL / bucket).iterdir():
            with contextlib.suppress(FileNotFoundError):
                if moment - entry.stat().st_mtime > STALE_SECONDS:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
    return removed


def _discard(entry: Path) -> None:
    if entry.is_dir() and not entry.is_symlink():
        shutil.rmtree(entry, ignore_errors=True)
    else:
        entry.unlink(missing_ok=True)


def _mtime(entry: Path) -> float:
    try:
        return entry.lstat().st_mtime
    except OSError:
        return 0.0


def run_once(runner: Runner = run_sandboxed) -> bool:
    pending = sorted((SPOOL / "requests").iterdir(), key=_mtime)
    for entry in pending:
        if not _ID.fullmatch(entry.name) or entry.is_symlink() or not entry.is_dir():
            _discard(entry)
            continue
        claimed = SPOOL / "work" / entry.name
        try:
            os.replace(entry, claimed)
        except FileNotFoundError:
            continue
        except OSError as exc:
            # A request this daemon cannot claim (e.g. written by another user) must
            # never take the converter down: drop it if possible, skip it otherwise.
            print(json.dumps({"event": "request_unclaimable", "id": entry.name,
                              "error": type(exc).__name__}), file=sys.stderr, flush=True)
            _discard(entry)
            continue
        _finish(claimed, process_request(claimed, runner))
        return True
    return False


def prepare_spool() -> None:
    for bucket in ("requests", "work", "done"):
        (SPOOL / bucket).mkdir(mode=0o770, parents=True, exist_ok=True)
    for orphan in (SPOOL / "work").iterdir():
        # A request claimed by a previous daemon instance never finished; fail it.
        _finish(orphan, {"ok": False, "reason": "converter_restarted", "results": {}})


def healthcheck() -> int:
    try:
        status = json.loads((SPOOL / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    fresh = time.time() - float(status.get("updated_at") or 0) <= STATUS_MAX_AGE_SECONDS
    return 0 if fresh and status.get("available") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return healthcheck()
    if args.probe:
        status = probe(scratch=Path(os.environ.get("TMPDIR", "/tmp")) / "aionex-blender-probe")
        print(json.dumps(status))
        return 0 if status["available"] else 1
    prepare_spool()
    stopping = False

    def _stop(*_args: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    status = probe()
    last_status = 0.0
    last_gc = 0.0
    while not stopping:
        now = time.time()
        if now - last_status >= 15:
            status = probe() if not status.get("available") else {**status, "updated_at": now}
            write_status(status)
            last_status = now
        if now - last_gc >= 60:
            collect_stale(now)
            last_gc = now
        if not (status.get("available") and run_once()):
            time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
