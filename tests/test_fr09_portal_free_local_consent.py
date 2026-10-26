"""Source contracts for localized truthful Free vs externally processed projects."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / "vip-frontend"
LOCALES = ("ar", "en", "de", "es", "fr", "tr")


def messages(lang: str) -> dict:
    return json.loads((PORTAL / "src/messages" / f"{lang}.json").read_text(encoding="utf-8"))


def test_six_locales_show_local_ollama_no_external_cost_without_release_approval():
    for lang in LOCALES:
        execution = messages(lang)["projects"]["execution"]
        local = execution["localConfirm"]
        external = execution["confirm"]
        assert "Ollama" in local, lang
        assert "0" in local, lang
        assert len(local) > 120, lang
        assert local != external, lang
        assert len(external) > 40, lang
        assert execution["threeDConfirm"], lang
        assert not any(token in local.lower() for token in ("sk-proj", "password", "secret"))


def test_portal_uses_free_plan_metadata_and_local_confirmation_not_paid_copy():
    source=(PORTAL/"src/components/pages/projects-client.tsx").read_text(encoding="utf-8")
    assert 'quota?.free_tier === true' in source
    assert 'user?.organization.plan.trim().toLowerCase() === "free"' in source
    assert 'user?.role.trim().toLowerCase() === "free user"' in source
    assert 'isFree' in source and '? t("execution.localConfirm")' in source
    assert 't("execution.confirm", {' in source
    assert 'window.confirm(t("execution.threeDConfirm"))' in source
    assert 'startProjectExecution(project.id, "full", !isFree)' in source
    assert 'startProjectExecution(project.id, "3d_full")' in source


def test_api_client_sends_real_explicit_consent_flag_preserving_3d_default():
    source=(PORTAL/"src/lib/api.ts").read_text(encoding="utf-8")
    assert 'confirmExternalProcessing = mode === "full" || mode === "3d_full"' in source
    assert "confirm_external_processing: confirmExternalProcessing" in source
    assert 'mode: "provider_neutral" | "full" | "3d_full" = "full"' in source
    assert "confirm_external_processing: true" not in source


def test_translation_keys_preserve_paid_and_3d_confirmations():
    for lang in LOCALES:
        root=messages(lang)["projects"]["execution"]
        keys={"confirm","localConfirm","threeDConfirm","start","starting"}
        assert keys.issubset(root),lang
        assert root["confirm"] != root["localConfirm"]
