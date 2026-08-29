from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.design_image_providers import (
    ProviderImageFailure,
    ProviderImageRequest,
    ProviderImageResult,
)
from app.services.design_image_runtime import DesignImageClaim
from app.services.design_image_worker import DesignImageWorker, LoadedImageExecution
from app.services.media_storage import LocalMediaObjectStore


class FakeAuthority:
    def __init__(self) -> None:
        self.claim_calls = 0
        self.completed: list[dict] = []
        self.failed: list[dict] = []

    async def claim(self):
        self.claim_calls += 1
        return DesignImageClaim("exec-1", "lease-1", 1)

    async def complete_bytes(self, claim, **kwargs):
        self.completed.append({"claim": claim, **kwargs})
        return {"status": "completed"}

    async def fail(self, claim, *, code: str, message: str, permanent: bool = False):
        self.failed.append({"claim": claim, "code": code, "message": message, "permanent": permanent})


class FakeAdapter:
    def __init__(self, result: ProviderImageResult | None = None, failure: ProviderImageFailure | None = None) -> None:
        self.result = result
        self.failure = failure
        self.calls = 0

    async def invoke(self, request, *, credential: str, base_url: str):
        self.calls += 1
        assert credential == "credential"
        assert base_url == "https://api.openai.com"
        if self.failure is not None:
            raise self.failure
        assert self.result is not None
        return self.result


class StubWorker(DesignImageWorker):
    def __init__(self, *, loaded: LoadedImageExecution, **kwargs) -> None:
        super().__init__(**kwargs)
        self.loaded = loaded

    async def _load_execution(self, claim):
        assert claim.execution_id == "exec-1"
        return self.loaded


def loaded() -> LoadedImageExecution:
    return LoadedImageExecution(
        request=ProviderImageRequest(
            provider="openai",
            model="gpt-image-2",
            operation="generate",
            prompt="governed prompt",
            output_format="png",
        ),
        credential="credential",
        base_url="https://api.openai.com",
    )


@pytest.mark.asyncio
async def test_worker_is_fail_closed_when_live_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DESIGN_IMAGE_LIVE_ENABLED", False)
    monkeypatch.setattr(settings, "DESIGN_IMAGE_WORKER_HEALTH_FILE", str(tmp_path / "health.json"))
    authority = FakeAuthority()
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={},
    )
    assert await worker.run_once() is False
    assert authority.claim_calls == 0
    payload = json.loads((tmp_path / "health.json").read_text())
    assert payload["status"] == "disabled"
    assert payload["live_enabled"] is False
    assert payload["secret_returned"] is False


@pytest.mark.asyncio
async def test_worker_completes_fake_provider_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DESIGN_IMAGE_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "DESIGN_IMAGE_WORKER_HEALTH_FILE", str(tmp_path / "health.json"))
    authority = FakeAuthority()
    adapter = FakeAdapter(
        ProviderImageResult(
            body=b"image-bytes",
            content_type="image/png",
            request_id="req-1",
            metadata={"status": "ok"},
            usage={"images": 1},
            actual_cost_usd=0.001,
        )
    )
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},
    )
    assert await worker.run_once() is True
    assert adapter.calls == 1
    assert len(authority.completed) == 1
    assert authority.completed[0]["provider_request_id"] == "req-1"
    assert authority.completed[0]["actual_cost_usd"] == 0.001
    assert authority.failed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "retryable", "permanent"),
    [
        ("provider_rate_limited", True, False),
        ("provider_transport", True, False),
        ("provider_auth", False, True),
        ("provider_billing", False, True),
    ],
)
async def test_worker_maps_retryability_to_durable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    retryable: bool,
    permanent: bool,
) -> None:
    monkeypatch.setattr(settings, "DESIGN_IMAGE_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "DESIGN_IMAGE_WORKER_HEALTH_FILE", str(tmp_path / "health.json"))
    authority = FakeAuthority()
    adapter = FakeAdapter(failure=ProviderImageFailure(code, retryable=retryable))
    worker = StubWorker(
        loaded=loaded(),
        authority=authority,  # type: ignore[arg-type]
        store=LocalMediaObjectStore(tmp_path / "objects"),
        adapters={"openai": adapter},
    )
    assert await worker.run_once() is True
    assert authority.completed == []
    assert authority.failed[0]["code"] == code
    assert authority.failed[0]["permanent"] is permanent
    assert "credential" not in authority.failed[0]["message"]


def test_design_image_worker_compose_is_governed_live_and_nonroot() -> None:
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "web-dashboard/docker-compose.production.yml",
        "deploy/production/docker-compose.production.yml",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        start = source.index("  design-image-worker:")
        tail = source.index("\n  three-d-worker:", start)
        block = source[start:tail]
        assert 'profiles: ["image-execution"]' in block
        assert 'user: "1000:1000"' in block
        assert 'DESIGN_IMAGE_LIVE_ENABLED: "true"' in block
        assert 'cap_drop: ["ALL"]' in block
        assert 'no-new-privileges:true' in block
        assert 'app.services.design_image_worker' in block
