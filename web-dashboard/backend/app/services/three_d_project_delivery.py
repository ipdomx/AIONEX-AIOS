"""Autonomous 3D web-project assembly, build, browser QA, and release evidence.

This module closes the gap between project-scoped GLB generation and a complete
self-contained 3D web delivery. It consumes verified AIOS project artifacts and can
optionally generate bounded missing assets through the configured server-side 3D provider,
then materializes the deterministic React Three Fiber runtime and performs a real
production build, runs local Chromium QA, evaluates 3D performance gates, and
returns evidence that can be merged into the governed project execution result.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import http.server
import httpx
import ipaddress
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import subprocess
import unicodedata
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from aios.three_d_web import (
    ApprovalDecision,
    AssetKind,
    BrowserRunReceipt,
    BrowserSpec,
    BrowserSupport,
    ConsoleRecord,
    EvidenceEntry,
    EvidenceKind,
    LifecycleInputs,
    PerformanceProfile,
    PerformanceSample,
    Project3DBlueprint,
    ScenarioResult,
    SceneAsset,
    SceneZone,
    ThreeDProjectLifecycle,
    ThreeDProjectPlanner,
    ThreeDRuntimeScaffoldBuilder,
    ViewportSpec,
    WebGLErrorRecord,
)
from aios.three_d_web.assets import AssetInspector


class ThreeDProjectDeliveryError(RuntimeError):
    """A complete 3D web delivery could not be proven safe/release-ready."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, fallback: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    normalized = "-".join(part for part in normalized.split("-") if part)
    return (normalized[:80] or fallback).strip("-")


def _load_staged_assets(manifest_path: str | Path | None) -> list[dict[str, Any]]:
    if not manifest_path:
        return []
    path = Path(manifest_path)
    if not path.is_file() or path.is_symlink():
        raise ThreeDProjectDeliveryError("3D asset staging manifest is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThreeDProjectDeliveryError("3D asset staging manifest is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ThreeDProjectDeliveryError("3D asset staging manifest has an unsupported schema")
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise ThreeDProjectDeliveryError("3D asset staging manifest is incomplete")
    assets: list[dict[str, Any]] = []
    root = path.parent.resolve()
    for index, raw in enumerate(raw_assets):
        if not isinstance(raw, dict):
            raise ThreeDProjectDeliveryError("3D staged asset entry is invalid")
        relative = PurePosixPath(str(raw.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".glb":
            raise ThreeDProjectDeliveryError("3D staged asset path is unsafe")
        resolved = (root / Path(*relative.parts)).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ThreeDProjectDeliveryError("3D staged asset escapes its staging root") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise ThreeDProjectDeliveryError("3D staged asset is unavailable")
        raw_digest = str(raw.get("sha256") or "").lower()
        if len(raw_digest) != 64 or _digest_file(resolved) != raw_digest:
            raise ThreeDProjectDeliveryError("3D staged asset failed integrity verification")
        declared_size = int(raw.get("size_bytes") or 0)
        if declared_size != resolved.stat().st_size or declared_size <= 0:
            raise ThreeDProjectDeliveryError("3D staged asset size does not match evidence")
        assets.append(
            {
                "artifact_id": str(raw.get("artifact_id") or f"artifact-{index+1}"),
                "job_id": str(raw.get("job_id") or ""),
                "provider": str(raw.get("provider") or "unknown"),
                "source": resolved,
                "sha256": raw_digest,
                "size_bytes": declared_size,
                "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            }
        )
    return assets


_TRIPO_BASE_URL = "https://openapi.tripo3d.ai/v3"
_TRIPO_API_VERSION = "v3"
_TRIPO_MODEL_VERSION = "P1-20260311"


def _bounded_provider_prompt(value: str, *, limit: int = 900) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = "".join(
        ch for ch in text
        if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )
    text = " ".join(text.split())
    return text[:limit].strip()


def _autonomous_asset_prompts(project_name: str, objective: str, count: int) -> tuple[str, ...]:
    context = _bounded_provider_prompt(f"{project_name}. {objective}", limit=560)
    roles = (
        "premium hero centerpiece that represents the product identity",
        "interactive architectural landmark for an immersive website section",
        "sleek navigation vehicle or drone that fits the project world",
        "supporting futuristic environment prop or technology pavilion",
        "distinct showcase object for a secondary experience zone",
        "lightweight decorative landmark for mobile and low-power devices",
    )
    return tuple(
        _bounded_provider_prompt(
            f"Create a production-ready low-poly PBR 3D asset: {roles[index]}. "
            f"Project context: {context}. Isolated object, clean topology, coherent scale, "
            "no text, no watermark, no background plane, suitable for real-time web rendering."
        )
        for index in range(max(0, min(count, len(roles))))
    )


def _public_https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ThreeDProjectDeliveryError("3D provider returned an unsafe artifact URL")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ThreeDProjectDeliveryError("3D provider artifact URL resolved to a local host")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise ThreeDProjectDeliveryError("3D provider artifact host could not be resolved") from exc
        if not addresses:
            raise ThreeDProjectDeliveryError("3D provider artifact host has no address")
        candidates = [ipaddress.ip_address(address) for address in addresses]
    else:
        candidates = [literal]
    if any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in candidates
    ):
        raise ThreeDProjectDeliveryError("3D provider artifact URL resolved to a non-public address")
    return value


class TripoTextToModelClient:
    """Minimal server-side Tripo text-to-GLB adapter for autonomous project assets."""

    def __init__(self, api_key: str, *, timeout_seconds: int = 300) -> None:
        self.api_key = api_key.strip()
        self.timeout_seconds = max(60, min(int(timeout_seconds), 900))
        if not self.api_key:
            raise ValueError("Tripo API key is required")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def available_credits(self) -> float:
        """Return conservative usable API credits without exposing wallet details."""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(15.0, connect=10.0), follow_redirects=False
            ) as client:
                data = self._payload(
                    client.get(f"{_TRIPO_BASE_URL}/account/balance", headers=self.headers)
                )
        except httpx.HTTPError as exc:
            raise ThreeDProjectDeliveryError(
                f"Tripo wallet preflight failed ({type(exc).__name__})"
            ) from exc
        try:
            balance = float(data.get("balance") or 0.0)
            frozen = float(data.get("frozen") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ThreeDProjectDeliveryError("Tripo wallet response is invalid") from exc
        return max(0.0, balance - frozen)

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise ThreeDProjectDeliveryError(
                f"Tripo provider returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ThreeDProjectDeliveryError("Tripo provider returned invalid JSON") from exc
        if not isinstance(body, dict) or int(body.get("code", -1)) != 0:
            raise ThreeDProjectDeliveryError("Tripo provider rejected the 3D generation request")
        data = body.get("data")
        if not isinstance(data, dict):
            raise ThreeDProjectDeliveryError("Tripo provider response is missing task data")
        return data

    def submit(self, prompt: str, *, seed: int, face_limit: int) -> str:
        body = {
            "prompt": _bounded_provider_prompt(prompt),
            "model": _TRIPO_MODEL_VERSION,
            "negative_prompt": "text, watermark, background plane, disconnected fragments, excessive polygons",
            "model_seed": int(seed),
            "face_limit": max(1000, min(int(face_limit), 12000)),
            "texture": True,
            "pbr": True,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False) as client:
                data = self._payload(
                    client.post(f"{_TRIPO_BASE_URL}/generation/text-to-model", headers=self.headers, json=body)
                )
        except httpx.HTTPError as exc:
            raise ThreeDProjectDeliveryError(
                f"Tripo provider submission failed ({type(exc).__name__})"
            ) from exc
        task_id = str(data.get("task_id") or "").strip()
        if not task_id or len(task_id) > 128:
            raise ThreeDProjectDeliveryError("Tripo provider did not return a valid task id")
        return task_id

    def wait(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False) as client:
                while time.monotonic() < deadline:
                    data = self._payload(
                        client.get(
                            f"{_TRIPO_BASE_URL}/tasks/{task_id}", headers=self.headers
                        )
                    )
                    status = str(data.get("status") or "").lower()
                    if status == "success":
                        return data
                    if status in {"failed", "banned", "expired", "cancelled", "unknown"}:
                        raise ThreeDProjectDeliveryError(
                            f"Tripo 3D task finalized without success ({status})"
                        )
                    time.sleep(2.0)
        except httpx.HTTPError as exc:
            raise ThreeDProjectDeliveryError(
                f"Tripo provider polling failed ({type(exc).__name__})"
            ) from exc
        raise ThreeDProjectDeliveryError("Tripo 3D task exceeded the bounded generation timeout")

    def download_glb(self, url: str, destination: Path, *, max_bytes: int = 6 * 1024 * 1024) -> None:
        current = _public_https_url(url)
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False) as client:
                for _ in range(4):
                    with client.stream("GET", current, headers={"Accept": "model/gltf-binary,application/octet-stream"}) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise ThreeDProjectDeliveryError("Tripo artifact redirect is missing a location")
                            current = _public_https_url(urljoin(current, location))
                            continue
                        if response.status_code >= 400:
                            raise ThreeDProjectDeliveryError(
                                f"Tripo artifact download returned HTTP {response.status_code}"
                            )
                        payload = bytearray()
                        for chunk in response.iter_bytes(1024 * 1024):
                            payload.extend(chunk)
                            if len(payload) > max_bytes:
                                raise ThreeDProjectDeliveryError("Tripo artifact exceeds the autonomous asset size limit")
                        if len(payload) < 20 or payload[:4] != b"glTF":
                            raise ThreeDProjectDeliveryError("Tripo artifact is not a valid GLB container")
                        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        with destination.open("xb") as stream:
                            stream.write(payload)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.chmod(destination, 0o600)
                        return
        except httpx.HTTPError as exc:
            raise ThreeDProjectDeliveryError(
                f"Tripo artifact download failed ({type(exc).__name__})"
            ) from exc
        raise ThreeDProjectDeliveryError("Tripo artifact exceeded the redirect limit")


def _autogenerate_tripo_assets(
    *, root: Path, project_name: str, objective: str, api_key: str, count: int
) -> list[dict[str, Any]]:
    prompts = _autonomous_asset_prompts(project_name, objective, count)
    if not prompts:
        return []
    client = TripoTextToModelClient(
        api_key,
        timeout_seconds=int(os.environ.get("PROJECT_3D_AUTOGEN_TIMEOUT_SECONDS", "300")),
    )
    task_ids = [
        client.submit(prompt, seed=24680 + index, face_limit=6000 if index < 2 else 4000)
        for index, prompt in enumerate(prompts)
    ]
    generated_root = root / "three-d-autogen"
    assets_root = generated_root / "assets"
    rows: list[dict[str, Any]] = []
    total = 0
    task_evidence: list[dict[str, Any]] = []
    for index, task_id in enumerate(task_ids):
        data = client.wait(task_id)
        output = data.get("output")
        if not isinstance(output, dict) or not str(output.get("model_url") or "").strip():
            raise ThreeDProjectDeliveryError("Tripo V3 task completed without a documented model URL")
        destination = assets_root / f"tripo-{index+1:02d}.glb"
        client.download_glb(str(output["model_url"]), destination)
        size = destination.stat().st_size
        total += size
        if total > 18 * 1024 * 1024:
            raise ThreeDProjectDeliveryError("Autonomous Tripo assets exceed the mobile delivery budget")
        digest = _digest_file(destination)
        rows.append(
            {
                "artifact_id": f"tripo:{task_id}",
                "job_id": task_id,
                "provider": "tripo3d",
                "source": destination,
                "sha256": digest,
                "size_bytes": size,
                "metadata": {
                    "api_version": _TRIPO_API_VERSION,
                    "model": _TRIPO_MODEL_VERSION,
                    "generation_mode": "text_to_model",
                    "credits_consumed": data.get("credits_consumed"),
                },
            }
        )
        task_evidence.append(
            {
                "task_id": task_id,
                "status": "success",
                "api_version": _TRIPO_API_VERSION,
                "model": _TRIPO_MODEL_VERSION,
                "sha256": digest,
                "size_bytes": size,
                "credits_consumed": data.get("credits_consumed"),
            }
        )
    generated_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_path = generated_root / "manifest.json"
    evidence_path.write_text(
        _canonical_json(
            {
                "schema_version": 1,
                "provider": "tripo3d",
                "api_version": _TRIPO_API_VERSION,
                "mode": "autonomous_text_to_model",
                "tasks": task_evidence,
                "total_bytes": total,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(evidence_path, 0o600)
    return rows


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _StaticServer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.port = _reserve_port()
        handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
            *args, directory=str(root), **kwargs
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_StaticServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _browser_qa(
    dist_root: Path,
    evidence_root: Path,
    *,
    asset_bytes_by_profile: Mapping[PerformanceProfile, int],
    bundle_bytes: int,
) -> tuple[tuple[BrowserRunReceipt, ...], tuple[PerformanceSample, ...]]:
    try:
        from selenium import webdriver  # type: ignore[import-not-found]
        from selenium.webdriver.chrome.options import Options  # type: ignore[import-not-found]
        from selenium.webdriver.chrome.service import Service  # type: ignore[import-not-found]
        from selenium.webdriver.common.by import By  # type: ignore[import-not-found]
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - production image only
        raise ThreeDProjectDeliveryError("3D browser QA runtime is unavailable") from exc

    chromium = shutil.which("chromium-browser") or shutil.which("chromium")
    chromedriver = shutil.which("chromedriver")
    xvfb = shutil.which("Xvfb")
    if not chromium or not chromedriver or not xvfb:
        raise ThreeDProjectDeliveryError(
            "Chromium/ChromeDriver/Xvfb is unavailable for 3D browser QA"
        )

    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    profiles = (
        (PerformanceProfile.DESKTOP, "desktop-1440", 1440, 900, False, 1.0),
        (PerformanceProfile.MOBILE, "mobile-390", 390, 844, True, 1.0),
        (PerformanceProfile.LOW_POWER, "low-power-360", 360, 640, True, 4.0),
    )
    receipts: list[BrowserRunReceipt] = []
    performance: list[PerformanceSample] = []

    display = ":99"
    old_display = os.environ.get("DISPLAY")
    old_libgl = os.environ.get("LIBGL_ALWAYS_SOFTWARE")
    xvfb_process = subprocess.Popen(
        [xvfb, display, "-screen", "0", "1600x1000x24", "+extension", "GLX", "+render"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    os.environ["DISPLAY"] = display
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    time.sleep(0.5)
    try:
        if xvfb_process.poll() is not None:
            raise ThreeDProjectDeliveryError("3D browser QA virtual display could not start")
        with _StaticServer(dist_root) as server:
            for profile, viewport_id, width, height, mobile, throttle in profiles:
                target = f"http://127.0.0.1:{server.port}/?aionex_profile={profile.value}"
                options = Options()
                options.binary_location = chromium
                for flag in (
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--enable-webgl",
                    "--ignore-gpu-blocklist",
                    "--use-gl=angle",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-sync",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--window-size={width},{height}",
                ):
                    options.add_argument(flag)
                options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
                driver = webdriver.Chrome(service=Service(chromedriver), options=options)
                try:
                    driver.set_window_size(width, height)
                    if throttle > 1:
                        try:
                            driver.execute_cdp_cmd(
                                "Emulation.setCPUThrottlingRate", {"rate": throttle}
                            )
                        except Exception:
                            throttle = 1.0
                    driver.get(target)
                    wait = WebDriverWait(driver, 35)
                    ready = bool(
                        wait.until(
                            lambda current: current.execute_script(
                                "return window.__AIOS_3D_READY__ === true && !!document.querySelector('canvas')"
                            )
                        )
                    )
                    canvas_ok = bool(
                        driver.execute_script(
                            "const c=document.querySelector('canvas'); return !!c && c.width>0 && c.height>0;"
                        )
                    )
                    metrics = (
                        driver.execute_script("return window.__AIOS_3D_METRICS__ || {};")
                        or {}
                    )
                    buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-zone-id]")
                    interaction_ok = bool(buttons)
                    if buttons:
                        zone_id = str(buttons[0].get_attribute("data-zone-id") or "")
                        buttons[0].click()
                        interaction_ok = bool(
                            wait.until(
                                lambda current: current.execute_script(
                                    "return window.__AIOS_TARGET_ZONE__ || null"
                                )
                                == zone_id
                            )
                        )
                        time.sleep(0.8)
                        metrics = (
                            driver.execute_script(
                                "return window.__AIOS_3D_METRICS__ || {};"
                            )
                            or metrics
                        )
                    camera_values = [
                        metrics.get(key)
                        for key in ("camera_x", "camera_y", "camera_z")
                    ]
                    camera_ok = all(
                        isinstance(value, (int, float))
                        and math.isfinite(float(value))
                        for value in camera_values
                    )
                    resource_names = driver.execute_script(
                        "return performance.getEntriesByType('resource').map((entry)=>entry.name);"
                    ) or []
                    loaded_glb_count = sum(
                        1 for value in resource_names
                        if str(value).split("?", 1)[0].lower().endswith((".glb", ".gltf"))
                    )
                    low_power_streaming_ok = (
                        profile != PerformanceProfile.LOW_POWER or loaded_glb_count == 0
                    )
                    logs = driver.get_log("browser")
                    console: list[ConsoleRecord] = []
                    webgl_errors: list[WebGLErrorRecord] = []
                    for entry in logs:
                        level = str(entry.get("level") or "info").lower()
                        message = str(entry.get("message") or "")[:1000]
                        if "webgl" in message.lower() and any(
                            word in message.lower() for word in ("error", "failed", "lost")
                        ):
                            webgl_errors.append(
                                WebGLErrorRecord(code="browser-console", message=message)
                            )
                        if level in {"severe", "error"}:
                            level = "error"
                        console.append(
                            ConsoleRecord(
                                level=level, message=message, source="chromium"
                            )
                        )
                    screenshot = evidence_root / f"{viewport_id}.png"
                    if (
                        not driver.save_screenshot(str(screenshot))
                        or not screenshot.is_file()
                    ):
                        raise ThreeDProjectDeliveryError(
                            "3D browser QA could not capture screenshot evidence"
                        )
                    evidence = (
                        EvidenceEntry(
                            evidence_id=f"screenshot-{viewport_id}",
                            kind=EvidenceKind.SCREENSHOT,
                            path=f"qa/{screenshot.name}",
                            sha256=_digest_file(screenshot),
                            viewport_id=viewport_id,
                            browser_id="chromium",
                        ),
                    )
                    scenarios = (
                        ScenarioResult(
                            "route-home",
                            ready and canvas_ok,
                            ("canvas-ready" if canvas_ok else "canvas-unavailable",),
                        ),
                        ScenarioResult(
                            "asset-world",
                            ready and not webgl_errors,
                            ("runtime-ready",),
                        ),
                        ScenarioResult(
                            "interaction-primary",
                            interaction_ok,
                            (
                                "zone-target-updated"
                                if interaction_ok
                                else "zone-target-failed"
                            ,),
                        ),
                        ScenarioResult(
                            "camera-follow-focus",
                            camera_ok,
                            ("camera-finite" if camera_ok else "camera-invalid",),
                        ),
                        ScenarioResult(
                            "low-power-asset-streaming",
                            low_power_streaming_ok,
                            (f"loaded-3d-resources:{loaded_glb_count}",),
                        ),
                    )
                    receipts.append(
                        BrowserRunReceipt(
                            browser=BrowserSpec(
                                "chromium", "chromium", BrowserSupport.SUPPORTED
                            ),
                            viewport=ViewportSpec(
                                viewport_id, width, height, 1.0, mobile
                            ),
                            console=tuple(console),
                            webgl_errors=tuple(webgl_errors),
                            scenarios=scenarios,
                            evidence=evidence,
                        )
                    )
                    fps = max(0.0, float(metrics.get("fps") or 0.0))
                    frame_ms = max(0.0, float(metrics.get("frame_time_ms") or 0.0))
                    draw_calls = max(0, int(metrics.get("draw_calls") or 0))
                    triangles = max(0, int(metrics.get("triangles") or 0))
                    profile_asset_bytes = max(0, int(asset_bytes_by_profile.get(profile, 0)))
                    framebuffer_estimate = width * height * 16
                    gpu_memory_estimate_mb = max(
                        1,
                        math.ceil(
                            (profile_asset_bytes * 1.5 + framebuffer_estimate + bundle_bytes)
                            / (1024 * 1024)
                        ),
                    )
                    performance.append(
                        PerformanceSample(
                            profile=profile,
                            fps=fps,
                            frame_time_ms=frame_ms,
                            draw_calls=draw_calls,
                            triangles=triangles,
                            asset_bytes=profile_asset_bytes,
                            bundle_bytes=bundle_bytes,
                            gpu_memory_mb=gpu_memory_estimate_mb,
                            timing_measurement_authoritative=False,
                        )
                    )
                finally:
                    driver.quit()
    finally:
        xvfb_process.terminate()
        try:
            xvfb_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            xvfb_process.kill()
        if old_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = old_display
        if old_libgl is None:
            os.environ.pop("LIBGL_ALWAYS_SOFTWARE", None)
        else:
            os.environ["LIBGL_ALWAYS_SOFTWARE"] = old_libgl
    return tuple(receipts), tuple(performance)


class ThreeDWebDeliveryBuilder:
    """Build a complete locally validated 3D web delivery for a user project."""

    BUILD_TIMEOUT_SECONDS = 300
    NPM_CI_TIMEOUT_SECONDS = 300

    def __init__(self, *, command_runner: CommandRunner = subprocess.run) -> None:
        self.command_runner = command_runner

    @staticmethod
    def _blueprint(
        *, project_id: str, project_name: str, objective: str, asset_records: Sequence[dict[str, Any]]
    ) -> Project3DBlueprint:
        scene_assets: list[SceneAsset] = []
        zones: list[SceneZone] = []
        for index, record in enumerate(asset_records):
            asset_id = f"asset-{index+1:02d}"
            filename = f"asset-{index+1:02d}.glb"
            scene_assets.append(
                SceneAsset(
                    asset_id=asset_id,
                    kind=AssetKind.GLB,
                    path=f"public/assets/{filename}",
                    required=True,
                    lazy=True,
                    lod_group=f"zone-{index+1:02d}",
                    checksum=str(record["sha256"]),
                )
            )
        zone_titles = (
            "Hero Experience",
            "Innovation Lab",
            "Services World",
            "Interactive Showcase",
            "Technology Hub",
            "Product Journey",
            "Contact Portal",
            "Future Lab",
        )
        zone_count = max(4, min(max(1, len(scene_assets)), len(zone_titles)))
        orbit = max(14.0, min(34.0, 8.0 + zone_count * 2.8))
        for index in range(zone_count):
            angle = (2.0 * math.pi * index / zone_count) - (math.pi / 2.0)
            asset_ids = (scene_assets[index].asset_id,) if index < len(scene_assets) else ()
            zones.append(
                SceneZone(
                    zone_id=f"zone-{index+1:02d}",
                    title=zone_titles[index],
                    position=(
                        round(math.cos(angle) * orbit, 3),
                        0.0,
                        round(math.sin(angle) * orbit, 3),
                    ),
                    radius=5.5,
                    asset_ids=asset_ids,
                    mobile_scale=0.72,
                    desktop_scale=1.0,
                )
            )
        return ThreeDProjectPlanner().plan(
            project_id=_safe_component(project_id, "aionex-3d-project"),
            title=project_name,
            objective=objective,
            zones=zones,
            assets=scene_assets,
            player_controller="adaptive-navigation",
            camera_mode="follow-and-focus",
        )

    def _run(self, command: list[str], *, cwd: Path, timeout: int, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        result = self.command_runner(
            command,
            cwd=str(cwd),
            env=dict(env or os.environ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            tail = (result.stdout or "")[-4000:]
            raise ThreeDProjectDeliveryError(
                f"3D project command failed safely ({command[0]} exit {result.returncode}): {tail}"
            )
        return result

    def build(
        self,
        *,
        project_id: str,
        project_name: str,
        objective: str,
        execution_root: str | Path,
        asset_manifest_path: str | Path | None,
    ) -> dict[str, Any]:
        root = Path(execution_root).resolve()
        final_delivery_root = (root / "delivery-package" / "3d-web").resolve()
        delivery_root = (root / ".3d-web-staging").resolve()
        try:
            final_delivery_root.relative_to(root)
            delivery_root.relative_to(root)
        except ValueError as exc:
            raise ThreeDProjectDeliveryError("3D delivery root escapes execution evidence") from exc
        if final_delivery_root.exists():
            raise ThreeDProjectDeliveryError("Final 3D delivery evidence already exists and will not be overwritten")
        if delivery_root.exists():
            # This directory is explicitly non-final staging. A reclaimed durable
            # execution may safely rebuild it; final evidence is never deleted.
            shutil.rmtree(delivery_root)
        delivery_root.mkdir(parents=True, mode=0o700)

        records = _load_staged_assets(asset_manifest_path)
        autogen_used = False
        autogen_status = "not_needed"
        autogen_message: str | None = None
        autogen_enabled = os.environ.get(
            "PROJECT_3D_AUTOGEN_ENABLED", "true"
        ).strip().lower() not in {"0", "false", "no", "off"}
        target_asset_count = max(
            1, min(int(os.environ.get("PROJECT_3D_AUTOGEN_ASSET_COUNT", "4")), 6)
        )
        tripo_key = os.environ.get("TRIPO_API_KEY", "").strip()
        missing_asset_count = max(0, target_asset_count - len(records))
        if autogen_enabled and missing_asset_count:
            if not tripo_key:
                autogen_status = "not_configured"
                autogen_message = (
                    "External text-to-3D generation is not configured; AIOS continued "
                    "with verified project assets and lightweight procedural zones."
                )
            else:
                try:
                    credit_per_asset = max(1.0, float(os.environ.get(
                        "PROJECT_3D_TRIPO_CREDITS_PER_ASSET", "40"
                    )))
                    available = TripoTextToModelClient(
                        tripo_key,
                        timeout_seconds=int(os.environ.get(
                            "PROJECT_3D_AUTOGEN_TIMEOUT_SECONDS", "300"
                        )),
                    ).available_credits()
                    affordable = min(missing_asset_count, int(available // credit_per_asset))
                    if affordable <= 0:
                        autogen_status = "insufficient_credit"
                        autogen_message = (
                            "External text-to-3D provider credit is currently insufficient; "
                            "AIOS continued without creating a billable provider task."
                        )
                    else:
                        generated = _autogenerate_tripo_assets(
                            root=root,
                            project_name=project_name,
                            objective=objective,
                            api_key=tripo_key,
                            count=affordable,
                        )
                        records.extend(generated)
                        autogen_used = bool(generated)
                        if affordable < missing_asset_count:
                            autogen_status = "partial_credit_limited"
                            autogen_message = (
                                "AIOS generated the provider-funded assets available within "
                                "the current wallet balance and used lightweight zones for the remainder."
                            )
                        else:
                            autogen_status = "completed"
                except ThreeDProjectDeliveryError:
                    autogen_status = "provider_unavailable"
                    autogen_message = (
                        "External text-to-3D generation was unavailable; AIOS continued "
                        "with verified project assets and lightweight procedural zones."
                    )
        blueprint = self._blueprint(
            project_id=project_id,
            project_name=project_name,
            objective=objective,
            asset_records=records,
        )
        scaffold = ThreeDRuntimeScaffoldBuilder().build(blueprint)
        ThreeDRuntimeScaffoldBuilder().materialize(scaffold, delivery_root)

        assets_root = delivery_root / "public" / "assets"
        assets_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        copied_assets: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            destination = assets_root / f"asset-{index+1:02d}.glb"
            shutil.copyfile(Path(record["source"]), destination)
            os.chmod(destination, 0o600)
            digest = _digest_file(destination)
            if digest != record["sha256"]:
                raise ThreeDProjectDeliveryError("3D delivery copy failed integrity verification")
            metadata = AssetInspector().inspect(blueprint.assets[index], delivery_root)
            copied_assets.append(
                {
                    "artifact_id": record["artifact_id"],
                    "job_id": record["job_id"],
                    "provider": record["provider"],
                    "path": str(blueprint.assets[index].path),
                    "sha256": digest,
                    "size_bytes": destination.stat().st_size,
                    "meshes": metadata.meshes,
                    "materials": metadata.materials,
                    "textures": metadata.textures,
                    "triangles": metadata.triangles,
                    "compression": sorted(item.value for item in metadata.compression),
                }
            )

        npm_cache = os.environ.get("PROJECT_EXECUTION_NPM_CACHE", "/var/lib/aionex/project-npm-cache")
        Path(npm_cache).mkdir(parents=True, exist_ok=True, mode=0o700)
        build_env = {
            **os.environ,
            "CI": "1",
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_CACHE": npm_cache,
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
        }
        self._run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=delivery_root,
            timeout=self.NPM_CI_TIMEOUT_SECONDS,
            env=build_env,
        )
        self._run(["npm", "run", "build"], cwd=delivery_root, timeout=self.BUILD_TIMEOUT_SECONDS, env=build_env)
        dist = delivery_root / "dist"
        if not (dist / "index.html").is_file():
            raise ThreeDProjectDeliveryError("3D production build did not create deployable output")
        shutil.rmtree(delivery_root / "node_modules", ignore_errors=True)
        bundle_files = [path for path in dist.rglob("*") if path.is_file() and not path.is_symlink()]
        model_payload_suffixes = {".glb", ".gltf"}
        runtime_bundle_files = [
            path for path in bundle_files if path.suffix.lower() not in model_payload_suffixes
        ]
        bundle_bytes = sum(path.stat().st_size for path in runtime_bundle_files)
        asset_bytes = sum(int(item["size_bytes"]) for item in copied_assets)
        lazy_asset_ids = {asset.asset_id for asset in blueprint.assets if asset.lazy}
        non_lazy_asset_bytes = sum(
            int(item["size_bytes"])
            for asset, item in zip(blueprint.assets, copied_assets, strict=True)
            if asset.asset_id not in lazy_asset_ids
        )
        asset_bytes_by_profile = {
            PerformanceProfile.DESKTOP: asset_bytes,
            PerformanceProfile.MOBILE: asset_bytes,
            PerformanceProfile.LOW_POWER: non_lazy_asset_bytes,
        }

        qa_root = delivery_root / "qa"
        browser_runs, performance_samples = _browser_qa(
            dist,
            qa_root,
            asset_bytes_by_profile=asset_bytes_by_profile,
            bundle_bytes=bundle_bytes,
        )
        build_manifest = {
            "schema_version": 1,
            "project_id": project_id,
            "runtime": "react-three-fiber",
            "asset_count": len(copied_assets),
            "assets": copied_assets,
            "dist_files": [
                {
                    "path": str(path.relative_to(delivery_root)),
                    "sha256": _digest_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in sorted(bundle_files)
            ],
            "browser_profiles": [sample.profile.value for sample in performance_samples],
            "profile_asset_bytes": {profile.value: value for profile, value in asset_bytes_by_profile.items()},
            "runtime_bundle_bytes_excluding_3d_models": bundle_bytes,
            "model_payload_bytes": asset_bytes,
            "low_power_lazy_assets_use_procedural_proxies": True,
            "autonomous_asset_generation_status": autogen_status,
            "autonomous_asset_generation_degraded": autogen_status not in {"not_needed", "completed"},
            "gpu_memory_values_are_conservative_estimates": True,
            "browser_timing_environment": "software-rendered Chromium under Xvfb; FPS/frame-time are retained as evidence but not used as production-device release thresholds",
            "external_runtime_dependencies": False,
        }
        manifest_path = delivery_root / "aionex-3d-build.json"
        manifest_path.write_text(_canonical_json(build_manifest), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        build_sha = _digest_file(manifest_path)
        deployment_receipt = f"local-staging://{project_id}/{build_sha}"
        rollback_receipt = f"immutable-delivery://{project_id}/{build_sha}"

        lifecycle = ThreeDProjectLifecycle().run(
            LifecycleInputs(
                blueprint=blueprint,
                project_root=delivery_root,
                browser_runs=browser_runs,
                performance_samples=performance_samples,
                production_build_passed=True,
                deployment_receipt=deployment_receipt,
                rollback_receipt=rollback_receipt,
                approval=ApprovalDecision(
                    approved=True,
                    approver="AIOS 3D validation gate",
                    reason=None,
                ),
            )
        )
        lifecycle_path = delivery_root / "aionex-3d-lifecycle.json"
        lifecycle_path.write_text(lifecycle.to_json() + "\n", encoding="utf-8")
        os.chmod(lifecycle_path, 0o600)
        final_delivery_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(delivery_root, final_delivery_root)

        return {
            "mode": "3d_full",
            "runtime": "react-three-fiber",
            "production_build_passed": True,
            "asset_count": len(copied_assets),
            "asset_providers": sorted({str(item["provider"]) for item in copied_assets}),
            "autonomous_asset_generation_used": autogen_used,
            "autonomous_asset_generation_status": autogen_status,
            "autonomous_asset_generation_degraded": autogen_status not in {"not_needed", "completed"},
            "autonomous_asset_generation_message": autogen_message,
            "procedural_fallback_used": not copied_assets,
            "bundle_bytes": bundle_bytes,
            "asset_bytes": asset_bytes,
            "browser_qa_passed": lifecycle.visual_qa.passed,
            "performance_passed": bool(lifecycle.performance_results)
            and all(item.passed for item in lifecycle.performance_results),
            "release_ready": lifecycle.release_ready,
            "release_reasons": list(lifecycle.release_gate.reasons),
            "aggregate_sha256": lifecycle.aggregate_sha256,
            "build_manifest_sha256": build_sha,
            "delivery_path": "delivery-package/3d-web",
            "deployment_evidence": deployment_receipt,
            "rollback_evidence": rollback_receipt,
            "performance": [
                {
                    **asdict(sample),
                    "profile": sample.profile.value,
                    "gpu_memory_estimated": True,
                }
                for sample in performance_samples
            ],
            "remediation": [
                {
                    "stage": item.stage.value,
                    "code": item.code,
                    "message": item.message,
                }
                for item in lifecycle.remediation
            ],
        }
