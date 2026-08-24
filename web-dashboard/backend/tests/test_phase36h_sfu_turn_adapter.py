from __future__ import annotations

from pathlib import Path

import pytest

from app.realtime.sfu import (
    COTURN_AMD64_DIGEST,
    LIVEKIT_EGRESS_AMD64_DIGEST,
    LIVEKIT_SERVER_AMD64_DIGEST,
    LiveKitCandidateAdapter,
    LiveKitCandidateConfig,
    RealtimeMediaConfigurationError,
    RealtimeMediaDisabledError,
    TurnServerReference,
)

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "deploy/phase36h/docker-compose.realtime.disabled.yml"
KUBERNETES = ROOT / "deploy/phase36h/kubernetes/realtime-media-disabled.yaml"


def _config() -> LiveKitCandidateConfig:
    return LiveKitCandidateConfig(
        signaling_url="wss://realtime.invalid",
        api_url="https://realtime-api.invalid",
        api_key_ref="file:///run/secrets/aionex/livekit-api-key",
        api_secret_ref="file:///run/secrets/aionex/livekit-api-secret",
        turn_servers=(
            TurnServerReference(urls=("stun://stun.invalid:3478",)),
            TurnServerReference(
                urls=("turn://turn.invalid:3478?transport=udp",),
                username_ref="env://AIOS_TURN_USERNAME",
                credential_ref="k8s-secret://aionex-realtime/turn-password",
            ),
        ),
    )


def test_candidate_configuration_is_secure_reference_only() -> None:
    config = _config()
    snapshot = config.safe_snapshot()
    assert snapshot["enabled"] is False
    assert snapshot["raw_api_key_returned"] is False
    assert snapshot["raw_api_secret_returned"] is False
    assert snapshot["egress_activated"] is False
    text = repr(snapshot)
    assert "livekit-api-key" not in text
    assert "livekit-api-secret" not in text
    assert "turn-password" not in text

    with pytest.raises(RealtimeMediaConfigurationError, match="reference"):
        LiveKitCandidateConfig(
            signaling_url="wss://realtime.invalid",
            api_url="https://realtime-api.invalid",
            api_key_ref="literal-key",
            api_secret_ref="literal-secret",
            turn_servers=(TurnServerReference(urls=("stun://stun.invalid:3478",)),),
        )


def test_candidate_urls_fail_closed() -> None:
    with pytest.raises(RealtimeMediaConfigurationError, match="wss"):
        LiveKitCandidateConfig(
            signaling_url="ws://realtime.invalid",
            api_url="https://realtime-api.invalid",
            api_key_ref="env://KEY",
            api_secret_ref="env://SECRET",
            turn_servers=(TurnServerReference(urls=("stun://stun.invalid:3478",)),),
        )
    with pytest.raises(RealtimeMediaConfigurationError, match="credential"):
        TurnServerReference(urls=("turn://turn.invalid:3478",))
    with pytest.raises(RealtimeMediaConfigurationError, match="transport"):
        TurnServerReference(
            urls=("turn://turn.invalid:3478?transport=sctp",),
            username_ref="env://TURN_USER",
            credential_ref="env://TURN_PASSWORD",
        )


def test_room_identity_is_opaque_stable_and_tenant_scoped() -> None:
    adapter = LiveKitCandidateAdapter(_config())
    first = adapter.plan_room(
        organization_id="tenant-secret-a", room_id="room-sensitive-1", max_participants=50
    )
    second = adapter.plan_room(
        organization_id="tenant-secret-a", room_id="room-sensitive-1", max_participants=50
    )
    other_tenant = adapter.plan_room(
        organization_id="tenant-secret-b", room_id="room-sensitive-1", max_participants=50
    )
    assert first == second
    assert first.provider_room_name != other_tenant.provider_room_name
    assert "tenant-secret" not in first.provider_room_name
    assert "room-sensitive" not in first.provider_room_name
    assert first.recording_enabled is False
    assert first.provider_mutation_allowed is False


@pytest.mark.asyncio
async def test_provider_mutation_is_hard_disabled() -> None:
    adapter = LiveKitCandidateAdapter(_config())
    plan = adapter.plan_room(
        organization_id="tenant-a", room_id="room-a", max_participants=5
    )
    with pytest.raises(RealtimeMediaDisabledError, match="disabled"):
        await adapter.provision_room(plan)


def test_candidate_images_are_immutable_and_profiles_open_no_ports() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    kubernetes = KUBERNETES.read_text(encoding="utf-8")
    assert LIVEKIT_SERVER_AMD64_DIGEST in compose
    assert COTURN_AMD64_DIGEST in compose
    assert LIVEKIT_SERVER_AMD64_DIGEST in kubernetes
    assert COTURN_AMD64_DIGEST in kubernetes
    assert LIVEKIT_EGRESS_AMD64_DIGEST not in compose
    assert "profiles: [\"phase36h-realtime-source-only\"]" in compose
    assert "ports:" not in compose
    assert "internal: true" in compose
    assert kubernetes.count("replicas: 0") == 2
    assert "kind: Service" not in kubernetes
    assert 'aionex.io/activation: "disabled"' in kubernetes
    assert 'policyTypes: ["Ingress", "Egress"]' in kubernetes


def test_source_adapter_has_no_network_client_or_runtime_sdk_dependency() -> None:
    source = (ROOT / "web-dashboard/backend/app/realtime/sfu.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import httpx",
        "import requests",
        "urllib.request",
        "from livekit",
        "import livekit",
        "socket.create_connection",
    ):
        assert forbidden not in source
