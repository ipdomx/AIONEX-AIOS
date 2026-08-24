from __future__ import annotations

import json
from pathlib import Path

import pytest

from aios.three_d_web.expansion import InteractiveTarget
from aios.three_d_web.two_d import TwoDProjectBuilder, TwoDProjectError


def test_animation_materializes_deterministically_and_verifies(tmp_path: Path) -> None:
    builder = TwoDProjectBuilder()
    one = tmp_path / "one"
    two = tmp_path / "two"
    first = builder.build(organization_id="tenant-a", project_id="animation-1", target=InteractiveTarget.TWO_D_ANIMATION, destination=one)
    second = builder.build(organization_id="tenant-a", project_id="animation-1", target=InteractiveTarget.TWO_D_ANIMATION, destination=two)
    assert first.aggregate_sha256 == second.aggregate_sha256
    assert first.organization_fingerprint != "tenant-a"
    assert first.provider_requests == 0
    assert first.external_spend_usd == 0
    assert builder.verify(first, one) == ()
    assert {item.path for item in first.artifacts} == {"index.html", "animation.js"}


def test_game_manifest_and_runtime_contract_are_offline(tmp_path: Path) -> None:
    root = tmp_path / "game"
    manifest = TwoDProjectBuilder().build(organization_id="tenant-b", project_id="game-1", target=InteractiveTarget.TWO_D_GAME, destination=root)
    game = json.loads((root / "game-manifest.json").read_text())
    assert game["offline"] is True
    assert game["controls"] == ["ArrowLeft", "ArrowRight", "Space"]
    source = (root / "game.js").read_text()
    for forbidden in ("fetch(", "WebSocket", "XMLHttpRequest", "http://", "https://"):
        assert forbidden not in source
    assert TwoDProjectBuilder().verify(manifest, root) == ()


def test_tampering_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    builder = TwoDProjectBuilder()
    manifest = builder.build(organization_id="tenant", project_id="safe", target=InteractiveTarget.TWO_D_GAME, destination=root)
    (root / "game.js").write_text("tampered")
    assert builder.verify(manifest, root) == ("game.js",)


def test_rejects_unsupported_target_unsafe_id_and_nonempty_destination(tmp_path: Path) -> None:
    builder = TwoDProjectBuilder()
    with pytest.raises(TwoDProjectError, match="only accepts"):
        builder.build(organization_id="tenant", project_id="p1", target=InteractiveTarget.THREE_D_SCENE, destination=tmp_path / "a")
    with pytest.raises(TwoDProjectError, match="unsafe"):
        builder.build(organization_id="tenant", project_id="../escape", target=InteractiveTarget.TWO_D_GAME, destination=tmp_path / "b")
    occupied = tmp_path / "occupied"; occupied.mkdir(); (occupied / "keep").write_text("x")
    with pytest.raises(TwoDProjectError, match="empty"):
        builder.build(organization_id="tenant", project_id="p2", target=InteractiveTarget.TWO_D_GAME, destination=occupied)
