"""Opt-in Meta Marketing credentials Compose overlay static security contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "web-dashboard/docker-compose.meta-operator-secrets.json"


def test_meta_overlay_only_amends_backend():
    obj = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert set(obj) == {"services"}
    assert set(obj["services"]) == {"backend"}
    assert set(obj["services"]["backend"]) == {"environment", "volumes"}


def test_meta_overlay_requires_independent_secret_sources():
    backend = json.loads(OVERLAY.read_text(encoding="utf-8"))["services"]["backend"]
    env = backend["environment"]
    assert env["AIOS_META_OWNED_TOKEN_FILE"] == "/run/operator-secrets/meta-owned-token"
    assert env["AIOS_META_SANDBOX_TOKEN_FILE"] == "/run/operator-secrets/meta-sandbox-token"
    assert env["AIOS_META_SANDBOX_AD_ACCOUNT_ID"].startswith(chr(36)+"{AIOS_META_SANDBOX_AD_ACCOUNT_ID:?")
    mounts = backend["volumes"]
    assert len(mounts) == 2
    assert {m["target"] for m in mounts} == {
        "/run/operator-secrets/meta-owned-token",
        "/run/operator-secrets/meta-sandbox-token",
    }
    expected = {"AIOS_META_OWNED_TOKEN_HOST_FILE", "AIOS_META_SANDBOX_TOKEN_HOST_FILE"}
    assert {m["source"].split(":?", 1)[0][2:] for m in mounts} == expected
    for mount in mounts:
        assert mount["type"] == "bind"
        assert mount["source"].startswith(chr(36)+"{")
        assert ":?" in mount["source"]
        assert mount["read_only"] is True
        assert mount["bind"] == {"create_host_path": False}
        assert mount["target"].startswith("/run/operator-secrets/")


def test_meta_overlay_does_not_enable_spend_or_publish_secret_values():
    text = OVERLAY.read_text(encoding="utf-8")
    for marker in ("sk-", "EAAB", "/root/.config/aionex/", "SPEND_ALLOWED", "AUTOMATIC_EXECUTION", "META_WRITE_ENABLED", "OPENAI_ADMIN_KEY"):
        assert marker not in text
