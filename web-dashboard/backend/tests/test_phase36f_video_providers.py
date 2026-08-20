from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.services.video_providers import (
    OpenAIVideoAdapter,
    ProviderVideoFailure,
    ProviderVideoInput,
    ProviderVideoRequest,
    openai_sora_fixed_cost,
)


def request(**overrides) -> ProviderVideoRequest:
    payload = {
        "provider": "openai",
        "model": "sora-2",
        "operation": "text-to-video",
        "prompt": "A cinematic product launch shot with physically plausible motion and clean brand staging.",
        "seconds": 4,
        "size": "1280x720",
    }
    payload.update(overrides)
    return ProviderVideoRequest(**payload)


@pytest.mark.asyncio
async def test_openai_submit_is_exact_multipart_create_and_returns_async_job() -> None:
    seen: dict[str, object] = {}

    async def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["path"] = req.url.path
        seen["authorization"] = req.headers.get("authorization")
        seen["content_type"] = req.headers.get("content-type")
        body = req.content.decode("utf-8", errors="ignore")
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "video_submit_1",
                "object": "video",
                "model": "sora-2",
                "status": "queued",
                "progress": 0,
                "created_at": int(datetime.now(UTC).timestamp()),
                "seconds": "4",
                "size": "1280x720",
                "prompt": request().prompt,
            },
        )

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    job = await adapter.submit(request(), credential="test-secret", base_url="https://api.openai.com")
    assert seen["method"] == "POST" and seen["path"] == "/v1/videos"
    assert seen["authorization"] == "Bearer test-secret"
    assert "multipart/form-data" in str(seen["content_type"])
    body = str(seen["body"])
    for value in ("sora-2", "1280x720", "4", request().prompt):
        assert value in body
    assert job.job_id == "video_submit_1" and job.state == "queued" and job.progress == 0


@pytest.mark.asyncio
async def test_openai_submit_reference_uses_governed_input_reference_file() -> None:
    seen: dict[str, object] = {}

    async def handler(req: httpx.Request) -> httpx.Response:
        body = req.content
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "video_ref_1",
                "object": "video",
                "model": "sora-2",
                "status": "queued",
                "progress": 0,
                "created_at": int(datetime.now(UTC).timestamp()),
                "seconds": "4",
                "size": "1280x720",
                "prompt": "Animate this logo",
            },
        )

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    ref = ProviderVideoInput(body=b"\x89PNG\r\n\x1a\nsynthetic", content_type="image/png", filename="logo.png")
    req = request(operation="logo-to-video", prompt="Animate this logo", reference=ref)
    job = await adapter.submit(req, credential="secret", base_url="https://api.openai.com")
    assert job.job_id == "video_ref_1"
    raw = bytes(seen["body"])
    assert b'input_reference' in raw and b'filename="logo.png"' in raw
    assert b"synthetic" in raw


@pytest.mark.asyncio
async def test_submission_timeout_and_5xx_are_ambiguous_not_auto_retryable() -> None:
    async def timeout_handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.submit(request(), credential="secret", base_url="https://api.openai.com")
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True
    assert caught.value.safe_to_resubmit is False

    async def five_hundred(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"type": "server_error", "code": "unavailable", "message": "do not retain"}})

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(five_hundred))
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.submit(request(), credential="secret", base_url="https://api.openai.com")
    assert caught.value.ambiguous_submission is True
    assert caught.value.metadata == {"http_status": 503, "type": "server_error", "code": "unavailable"}
    assert "message" not in caught.value.metadata


@pytest.mark.asyncio
async def test_rate_limit_is_explicit_safe_to_resubmit_rejection() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"type": "rate_limit", "code": "rate_limited"}})

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.submit(request(), credential="secret", base_url="https://api.openai.com")
    assert caught.value.code == "provider_rate_limited"
    assert caught.value.retryable is True
    assert caught.value.safe_to_resubmit is True
    assert caught.value.ambiguous_submission is False


@pytest.mark.asyncio
async def test_malformed_success_is_ambiguous_because_job_may_have_been_created() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "video", "status": "queued"})

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.submit(request(), credential="secret", base_url="https://api.openai.com")
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True


@pytest.mark.asyncio
async def test_reconcile_adopts_only_one_exact_recent_text_job() -> None:
    now = int(datetime.now(UTC).timestamp())
    prompt = request().prompt

    async def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/videos":
            assert req.url.params.get("order") == "desc"
            return httpx.Response(200, json={"object": "list", "data": [{"id": "video_match"}, {"id": "video_other"}]})
        job_id = req.url.path.rsplit("/", 1)[-1]
        if job_id == "video_match":
            return httpx.Response(200, json={
                "id": job_id, "object": "video", "model": "sora-2", "status": "in_progress",
                "progress": 35, "created_at": now, "seconds": "4", "size": "1280x720", "prompt": prompt,
            })
        return httpx.Response(200, json={
            "id": job_id, "object": "video", "model": "sora-2", "status": "queued",
            "progress": 0, "created_at": now, "seconds": "4", "size": "1280x720", "prompt": "different",
        })

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    job = await adapter.reconcile(
        request(),
        submitted_at=datetime.now(UTC),
        credential="secret",
        base_url="https://api.openai.com",
    )
    assert job.job_id == "video_match" and job.state == "in_progress" and job.progress == 35


@pytest.mark.asyncio
async def test_reconcile_fails_closed_on_multiple_matches_and_on_reference_request() -> None:
    now = int(datetime.now(UTC).timestamp())

    async def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/videos":
            return httpx.Response(200, json={"data": [{"id": "video_a"}, {"id": "video_b"}]})
        job_id = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={
            "id": job_id, "object": "video", "model": "sora-2", "status": "queued",
            "progress": 0, "created_at": now, "seconds": "4", "size": "1280x720", "prompt": request().prompt,
        })

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.reconcile(
            request(), submitted_at=datetime.now(UTC), credential="secret", base_url="https://api.openai.com"
        )
    assert caught.value.code == "provider_submission_reconcile_not_unique"
    assert caught.value.metadata == {"candidate_count": 2}

    ref = ProviderVideoInput(body=b"\x89PNGsynthetic", content_type="image/png")
    with pytest.raises(ProviderVideoFailure) as caught:
        await adapter.reconcile(
            request(operation="image-to-video", reference=ref),
            submitted_at=datetime.now(UTC),
            credential="secret",
            base_url="https://api.openai.com",
        )
    assert caught.value.code == "provider_submission_ambiguous_reference"


@pytest.mark.asyncio
async def test_retrieve_terminal_job_and_download_mp4_are_separate_bounded_calls() -> None:
    mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"

    async def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/content"):
            return httpx.Response(200, headers={"content-type": "video/mp4"}, content=mp4)
        return httpx.Response(200, json={
            "id": "video_done", "object": "video", "model": "sora-2", "status": "completed",
            "progress": 100, "created_at": int(datetime.now(UTC).timestamp()), "completed_at": int(datetime.now(UTC).timestamp()),
            "seconds": "4", "size": "1280x720", "prompt": request().prompt,
        })

    adapter = OpenAIVideoAdapter(transport=httpx.MockTransport(handler), max_content_bytes=1024)
    job = await adapter.retrieve("video_done", credential="secret", base_url="https://api.openai.com")
    assert job.state == "completed" and job.progress == 100
    content = await adapter.download_content("video_done", credential="secret", base_url="https://api.openai.com")
    assert content.content_type == "video/mp4" and content.body == mp4


def test_openai_sora_fixed_second_cost_is_explicit_and_fails_closed_outside_table() -> None:
    cost, evidence = openai_sora_fixed_cost(request())
    assert cost == pytest.approx(0.4)
    assert evidence == {
        "pricing_revision": "2026-08-20",
        "pricing_unit": "second",
        "price_per_second_usd": 0.10,
        "model": "sora-2",
        "size": "1280x720",
        "seconds": 4,
    }
    pro_cost, _ = openai_sora_fixed_cost(request(model="sora-2-pro", seconds=8))
    assert pro_cost == pytest.approx(2.4)
    with pytest.raises(ProviderVideoFailure, match="Video provider request failed"):
        openai_sora_fixed_cost(request(size="1792x1024"))
