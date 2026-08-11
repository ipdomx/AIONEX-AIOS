from __future__ import annotations

import pytest

from app.services import three_d_project_delivery as delivery


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, responses: list[dict], calls: list[dict], **_kwargs) -> None:
        self.responses = responses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, *, headers: dict, json: dict):
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return _FakeResponse(self.responses.pop(0))

    def get(self, url: str, *, headers: dict):
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return _FakeResponse(self.responses.pop(0))


def test_autonomous_prompts_are_bounded_coherent_and_multi_zone() -> None:
    prompts = delivery._autonomous_asset_prompts(
        "Orbital Commerce",
        "Build an immersive product website with premium technology, navigation and interactive service zones.",
        4,
    )
    assert len(prompts) == 4
    assert all(20 < len(item) <= 900 for item in prompts)
    assert all("Orbital Commerce" in item for item in prompts)
    assert len(set(prompts)) == 4


def test_tripo_text_to_model_submission_uses_current_bounded_contract(monkeypatch) -> None:
    calls: list[dict] = []
    responses = [{"code": 0, "data": {"task_id": "task-123"}}]
    monkeypatch.setattr(
        delivery.httpx,
        "Client",
        lambda **kwargs: _FakeClient(responses, calls, **kwargs),
    )
    client = delivery.TripoTextToModelClient("server-secret")
    task_id = client.submit("a premium product hero object", seed=7, face_limit=6000)
    assert task_id == "task-123"
    assert len(calls) == 1
    request = calls[0]
    assert request["url"] == "https://api.tripo3d.ai/v2/openapi/task"
    assert request["json"] == {
        "type": "text_to_model",
        "model_version": "P1-20260311",
        "prompt": "a premium product hero object",
        "negative_prompt": "text, watermark, background plane, disconnected fragments, excessive polygons",
        "model_seed": 7,
        "face_limit": 6000,
        "texture": True,
        "pbr": True,
    }
    assert request["headers"]["Authorization"] == "Bearer server-secret"


def test_tripo_polling_accepts_only_documented_success(monkeypatch) -> None:
    calls: list[dict] = []
    responses = [
        {"code": 0, "data": {"task_id": "task-123", "status": "running", "output": {}}},
        {
            "code": 0,
            "data": {
                "task_id": "task-123",
                "status": "success",
                "output": {"model": "https://cdn.example.test/model.glb"},
                "consumed_credit": 12,
            },
        },
    ]
    monkeypatch.setattr(
        delivery.httpx,
        "Client",
        lambda **kwargs: _FakeClient(responses, calls, **kwargs),
    )
    monkeypatch.setattr(delivery.time, "sleep", lambda _seconds: None)
    result = delivery.TripoTextToModelClient("server-secret").wait("task-123")
    assert result["status"] == "success"
    assert result["output"]["model"].endswith("model.glb")
    assert [item["method"] for item in calls] == ["GET", "GET"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/model.glb",
        "https://127.0.0.1/model.glb",
        "https://10.0.0.2/model.glb",
        "https://localhost/model.glb",
        "https://user:pass@example.com/model.glb",
    ],
)
def test_provider_artifact_url_rejects_non_public_or_unsafe_targets(url: str) -> None:
    with pytest.raises(delivery.ThreeDProjectDeliveryError):
        delivery._public_https_url(url)


def test_tripo_wallet_preflight_returns_conservative_available_credit(monkeypatch) -> None:
    calls: list[dict] = []
    responses = [{"code": 0, "data": {"balance": 75, "frozen": 15}}]
    monkeypatch.setattr(
        delivery.httpx,
        "Client",
        lambda **kwargs: _FakeClient(responses, calls, **kwargs),
    )
    available = delivery.TripoTextToModelClient("server-secret").available_credits()
    assert available == 60
    assert calls == [
        {
            "method": "GET",
            "url": "https://api.tripo3d.ai/v2/openapi/user/balance",
            "headers": {
                "Authorization": "Bearer server-secret",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        }
    ]
