"""Offline verification for the live-disabled Phase 36F video provider worker image."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.config import settings
from app.services.media_ffmpeg import FFmpegRuntime
from app.services.video_provider_worker import VideoProviderWorker


def main() -> int:
    if settings.VIDEO_EXECUTION_LIVE_ENABLED:
        raise RuntimeError("video provider verification requires live execution disabled")
    preflight = FFmpegRuntime(timeout_seconds=30).preflight()
    if preflight.get("version") != "9.0":
        raise RuntimeError("video provider worker FFmpeg preflight failed")
    worker = VideoProviderWorker()
    worked = asyncio.run(worker.run_once())
    if worked:
        raise RuntimeError("disabled video provider worker unexpectedly claimed work")
    health = json.loads(Path(settings.VIDEO_EXECUTION_WORKER_HEALTH_FILE).read_text(encoding="utf-8"))
    if health.get("status") != "disabled" or health.get("live_enabled") is not False:
        raise RuntimeError("video provider worker did not remain disabled")
    if health.get("secret_returned") is not False:
        raise RuntimeError("video provider worker health secret boundary failed")
    print(json.dumps({
        "preflight": {"engine": preflight.get("engine"), "version": preflight.get("version")},
        "health": {
            "status": health.get("status"),
            "live_enabled": health.get("live_enabled"),
            "cycles": health.get("cycles"),
            "errors": health.get("errors"),
        },
        "provider_requests": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
