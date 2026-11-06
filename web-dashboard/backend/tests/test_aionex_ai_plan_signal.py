"""Roadmap 5.2: signed X-AIONEX-Plan priority headers for the AIONEX AI gateway."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app.services import ai_runtime_service
from app.services import aionex_ai_plan_signal as signal
from app.services import project_ai_structured_adapter as structured

SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _reference_signature(secret: bytes, plan: str, ts: str, raw: bytes) -> str:
    """Verbatim from the AIONEX AI W02 contract example (gateway side)."""
    msg = "%s\n%s\n%s" % (plan, ts, hashlib.sha256(raw).hexdigest())
    return hmac.new(secret, msg.encode(), hashlib.sha256).hexdigest()


def _gateway_verifies(secret: bytes, headers: dict[str, str], raw: bytes, now: int) -> bool:
    plan = headers["X-AIONEX-Plan"]
    ts = headers["X-AIONEX-Plan-Ts"]
    if plan not in {"free", "paid", "owner"} or not ts.isdigit() or abs(now - int(ts)) > 120:
        return False
    expected = _reference_signature(secret, plan, ts, raw)
    return hmac.compare_digest(expected, headers["X-AIONEX-Plan-Sig"].lower())


@pytest.fixture
def secret_file(tmp_path, monkeypatch):
    path = tmp_path / "aionex-ai-plan.secret"
    path.write_text(f"  {SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(signal.settings, "AIONEX_AI_PLAN_SECRET_FILE", str(path))
    return path


@pytest.fixture
def no_secret(monkeypatch):
    monkeypatch.setattr(signal.settings, "AIONEX_AI_PLAN_SECRET_FILE", "")


@pytest.mark.parametrize("plan", ["free", "paid", "owner"])
def test_signature_matches_reference_implementation(secret_file, plan):
    raw = signal.encode_json_body({"model": "aionex-ai", "messages": [{"role": "user", "content": "سلام"}]})
    headers = signal.plan_headers(raw, plan=plan, now=1_800_000_000)
    assert headers["X-AIONEX-Plan"] == plan
    assert headers["X-AIONEX-Plan-Ts"] == "1800000000"
    sig = headers["X-AIONEX-Plan-Sig"]
    assert len(sig) == 64 and sig == sig.lower()
    assert sig == _reference_signature(SECRET.encode(), plan, "1800000000", raw)
    assert _gateway_verifies(SECRET.encode(), headers, raw, 1_800_000_119)
    assert not _gateway_verifies(SECRET.encode(), headers, raw, 1_800_000_121)
    assert not _gateway_verifies(SECRET.encode(), headers, raw + b" ", 1_800_000_000)


def test_unknown_or_missing_plan_is_signed_as_free(secret_file):
    raw = b"{}"
    assert signal.plan_headers(raw, plan="enterprise", now=1)["X-AIONEX-Plan"] == "free"
    assert signal.plan_headers(raw, now=1)["X-AIONEX-Plan"] == "free"
    with signal.plan_context("paid"):
        assert signal.plan_headers(raw, now=1)["X-AIONEX-Plan"] == "paid"
    assert signal.plan_headers(raw, now=1)["X-AIONEX-Plan"] == "free"


def test_no_headers_without_a_usable_secret(tmp_path, monkeypatch, no_secret):
    assert signal.read_plan_secret() is None
    assert signal.plan_headers(b"{}", plan="owner") == {}
    assert signal.signed_request("ollama", "aionex-ai", {"a": 1}) == (None, {})
    missing = tmp_path / "missing.secret"
    monkeypatch.setattr(signal.settings, "AIONEX_AI_PLAN_SECRET_FILE", str(missing))
    assert signal.read_plan_secret() is None
    short = tmp_path / "short.secret"
    short.write_text("tooshort\n", encoding="utf-8")
    monkeypatch.setattr(signal.settings, "AIONEX_AI_PLAN_SECRET_FILE", str(short))
    assert signal.read_plan_secret() is None
    assert signal.plan_headers(b"{}", plan="paid") == {}


def test_secret_whitespace_is_stripped_and_only_aionex_ai_is_signed(secret_file):
    assert signal.read_plan_secret() == SECRET.encode()
    assert signal.is_aionex_ai_target("ollama", "aionex-ai")
    assert signal.is_aionex_ai_target("ollama", "aionex-ai:latest")
    assert not signal.is_aionex_ai_target("ollama", "gemma3:4b")
    assert not signal.is_aionex_ai_target("openai", "aionex-ai")
    assert signal.signed_request("ollama", "qwen2.5:1.5b", {"a": 1}) == (None, {})


def _ollama_stub(captured: dict):
    async def stub(method, url, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        return {"model": "aionex-ai", "message": {"content": "ok"}, "prompt_eval_count": 3, "eval_count": 2}, 1.0

    return stub


@pytest.mark.anyio
async def test_chat_request_signs_the_exact_bytes_sent(secret_file, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(ai_runtime_service, "_request_json", _ollama_stub(captured))
    monkeypatch.setattr(ai_runtime_service, "provider_credential", lambda _p: None)
    provider = SimpleNamespace(type="ollama", config={}, base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="aionex-ai", temperature=0.2, system_prompt="")
    with signal.plan_context("owner"):
        result = await ai_runtime_service._execute_provider(provider, agent, "مرحبا")
    assert result["text"] == "ok"
    raw = captured["raw_body"]
    assert isinstance(raw, bytes)
    assert json.loads(raw) == captured["json_body"]
    headers = captured["headers"]
    assert headers["X-AIONEX-Plan"] == "owner"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-AIONEX-Plan-Sig"] == _reference_signature(
        SECRET.encode(), "owner", headers["X-AIONEX-Plan-Ts"], raw
    )


@pytest.mark.anyio
async def test_chat_request_is_unchanged_without_secret(no_secret, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(ai_runtime_service, "_request_json", _ollama_stub(captured))
    monkeypatch.setattr(ai_runtime_service, "provider_credential", lambda _p: None)
    provider = SimpleNamespace(type="ollama", config={}, base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="aionex-ai", temperature=0.2, system_prompt="")
    with signal.plan_context("paid"):
        await ai_runtime_service._execute_provider(provider, agent, "hello")
    assert "raw_body" not in captured
    assert captured["headers"] == {"Content-Type": "application/json"}


@pytest.mark.anyio
async def test_project_ai_local_role_is_signed(secret_file, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(structured, "_request_json", _ollama_stub(captured))
    provider = SimpleNamespace(type="ollama", base_url="http://127.0.0.1:11434")
    agent = SimpleNamespace(model="aionex-ai", temperature=0.2, system_prompt="")
    with signal.plan_context("paid"):
        await structured.execute_bounded_project_ollama_role(
            provider, agent, "Synthetic reviewer role", task_max_tokens=64
        )
    raw = captured["raw_body"]
    assert json.loads(raw) == captured["json_body"]
    headers = captured["headers"]
    assert headers["X-AIONEX-Plan"] == "paid"
    assert headers["X-AIONEX-Plan-Sig"] == _reference_signature(
        SECRET.encode(), "paid", headers["X-AIONEX-Plan-Ts"], raw
    )


@pytest.mark.anyio
async def test_plan_context_reaches_wait_for_tasks(secret_file):
    async def inner() -> str:
        return signal.plan_headers(b"{}", now=1)["X-AIONEX-Plan"]

    with signal.plan_context("paid"):
        assert await asyncio.wait_for(inner(), timeout=5) == "paid"


class _PlanSession:
    def __init__(self, *, role: str | None = None, prices: list | None = None) -> None:
        self.role = role
        self.prices = prices or []

    async def scalar(self, _statement):
        return self.role

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: list(self.prices))


@pytest.mark.anyio
async def test_plan_mapping_owner_paid_free(monkeypatch):
    from app.services import security_entitlement

    plan = SimpleNamespace(id="plan-pro", code="pro")
    current: dict = {"plan": plan}

    async def active_plan(_session, organization_id):
        assert organization_id == "org-1"
        return current["plan"]

    monkeypatch.setattr(security_entitlement, "active_subscription_plan", active_plan)
    paid_price = SimpleNamespace(enabled=True, amount_minor=4900)
    free_price = SimpleNamespace(enabled=True, amount_minor=0)
    disabled_price = SimpleNamespace(enabled=False, amount_minor=4900)

    assert await signal.resolve_plan(_PlanSession(), organization_id="org-1", role_name="Super Owner") == "owner"
    assert (
        await signal.resolve_plan(_PlanSession(role="Super Owner"), organization_id="org-1", user_id="u-1")
        == "owner"
    )
    assert (
        await signal.resolve_plan(_PlanSession(prices=[paid_price]), organization_id="org-1", role_name="Member")
        == "paid"
    )
    assert (
        await signal.resolve_plan(
            _PlanSession(prices=[free_price, disabled_price]), organization_id="org-1", role_name="Member"
        )
        == "free"
    )
    current["plan"] = None
    assert await signal.resolve_plan(_PlanSession(), organization_id="org-1", user_id="u-2") == "free"


@pytest.mark.anyio
async def test_plan_lookup_is_skipped_without_secret_or_for_other_models(no_secret):
    # ``session=None`` proves no database access happens on these paths.
    assert (
        await signal.plan_for_dispatch(
            None, provider_type="ollama", model="aionex-ai", organization_id="org-1"
        )
        is None
    )


@pytest.mark.anyio
async def test_plan_lookup_is_skipped_for_other_models(secret_file):
    assert (
        await signal.plan_for_dispatch(
            None, provider_type="ollama", model="gemma3:4b", organization_id="org-1"
        )
        is None
    )
