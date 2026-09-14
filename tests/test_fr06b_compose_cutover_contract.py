from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B2-compose-cutover-contract.json"
)
B1_CONTRACT = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B1-asset-vault-copy-contract.json"
)
OVERLAY = ROOT / "web-dashboard" / "docker-compose.fr06-assets.yml"
VALIDATOR = ROOT / "scripts" / "security" / "fr06b_validate_compose_overlay.py"
RECEIPT = (
    ROOT / "docs" / "project" / "receipts" / "FR-06B2-compose-cutover.md"
)
PROOF = (
    ROOT
    / "docs"
    / "project"
    / "receipts"
    / "FR-06B2-compose-render-proof.json"
)


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _load_validator():
    spec = importlib.util.spec_from_file_location("fr06b_overlay_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _service_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    in_services = False
    for line in text.splitlines(keepends=True):
        if line == "services:\n":
            in_services = True
            continue
        if in_services and line == "volumes:\n":
            break
        if not in_services:
            continue
        match = re.fullmatch(r"  ([a-z0-9-]+):\n", line)
        if match:
            current = match.group(1)
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "".join(lines) for name, lines in sections.items()}


def _expected_records(contract: dict) -> list[dict]:
    records: list[dict] = []
    for root in contract["matrix"]["roots"]:
        for consumer in root["consumers"]:
            records.append(
                {
                    **consumer,
                    "legacy_source": root["compose_volume"],
                    "overlay_source": root["overlay_volume"],
                    "subpath": root["target_subpath"],
                }
            )
    return records


def test_fr06b2_matrix_covers_every_root_mount_and_profile() -> None:
    contract = _json(CONTRACT)
    matrix = contract["matrix"]
    records = _expected_records(contract)
    b1_roots = {
        item["compose_volume"] for item in _json(B1_CONTRACT)["source_roots"]
    }
    assert matrix["root_count"] == 11
    assert {root["compose_volume"] for root in matrix["roots"]} == b1_roots
    assert matrix["protected_mount_count"] == len(records) == 54
    assert matrix["service_definition_count"] == 22
    assert len(matrix["affected_services"]) == 22
    assert len(matrix["runtime_writer_services"]) == 18
    assert matrix["initializer_services"] == [
        "backup-asset-root-init",
        "realtime-recording-init",
    ]
    assert matrix["read_only_only_services"] == [
        "backup-worker",
        "security-scan-worker",
    ]
    assert matrix["compose_profile_scope"] == "*"
    assert matrix["latent_profile_service_included"] == (
        "audio-song-worker-secondary"
    )
    assert len({(item["service"], item["target"]) for item in records}) == 54
    assert all(item["access"] in {"ro", "rw"} for item in records)
    assert all(
        item["role"] in {"runtime_writer", "runtime_reader", "initializer"}
        for item in records
    )


def test_fr06b2_overlay_is_additive_explicit_and_complete() -> None:
    contract = _json(CONTRACT)
    records = _expected_records(contract)
    text = OVERLAY.read_text(encoding="utf-8")
    sections = _service_sections(text)
    assert set(sections) == set(contract["matrix"]["affected_services"])
    assert text.count("      - type: volume\n") == 54
    assert text.count("          subpath: ") == 54
    assert "    name: aionex-fr06-asset-vault\n    external: true\n" in text
    assert (
        "    name: aionex-fr06-project-execution-vault\n"
        "    external: true\n"
    ) in text
    for forbidden in ("    image:", "    command:", "    restart:", "    ports:", "type: bind"):
        assert forbidden not in text

    legacy_sources = {
        root["compose_volume"] for root in contract["matrix"]["roots"]
    }
    for source in legacy_sources:
        assert f"        source: {source}\n" not in text

    by_service: dict[str, list[dict]] = {}
    for record in records:
        by_service.setdefault(record["service"], []).append(record)
        block = (
            "      - type: volume\n"
            f"        source: {record['overlay_source']}\n"
            f"        target: {json.dumps(record['target'])}\n"
            f"        read_only: {'true' if record['access'] == 'ro' else 'false'}\n"
            "        volume:\n"
            f"          subpath: {record['subpath']}\n"
        )
        assert sections[record["service"]].count(block) == 1
    for service, expected in by_service.items():
        assert sections[service].count("      - type: volume\n") == len(expected)


def test_fr06b2_validator_fails_closed_on_missing_or_extra_mount() -> None:
    module = _load_validator()
    contract = _json(CONTRACT)
    expected = module._expected_mounts(contract)
    config: dict = {"services": {}}
    for (service, target), wanted in expected.items():
        definition = config["services"].setdefault(service, {"volumes": []})
        definition["volumes"].append(
            {
                "type": "volume",
                "source": wanted["overlay_source"],
                "target": target,
                "read_only": wanted["read_only"],
                "volume": {"subpath": wanted["subpath"]},
            }
        )
    module._assert_overlay_matrix(config, expected)

    missing = json.loads(json.dumps(config))
    first_service, first_target = next(iter(expected))
    missing["services"][first_service]["volumes"] = [
        mount
        for mount in missing["services"][first_service]["volumes"]
        if mount["target"] != first_target
    ]
    with pytest.raises(module.ContractError, match="matrix drifted"):
        module._assert_overlay_matrix(missing, expected)

    extra = json.loads(json.dumps(config))
    extra["services"][first_service]["volumes"].append(
        {
            "type": "volume",
            "source": "fr06_asset_vault",
            "target": "/unexpected",
            "read_only": True,
            "volume": {"subpath": "three_d_asset_data"},
        }
    )
    with pytest.raises(module.ContractError, match="outside the approved matrix"):
        module._assert_overlay_matrix(extra, expected)


def test_fr06b2_validator_is_render_only_and_uses_no_shell() -> None:
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'command.extend(["config", "--format", "json"])' in source
    assert '["docker", "compose", "version", "--short"]' in source
    assert "shell=True" not in source
    for forbidden_token in (
        '"up"',
        '"start"',
        '"restart"',
        '"create"',
        "cryptsetup",
        "systemctl",
    ):
        assert forbidden_token not in source


def test_fr06b2_rendered_overlay_matches_example_environment() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    version = subprocess.run(
        ["docker", "compose", "version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if version.returncode != 0:
        pytest.skip("Docker Compose plugin is unavailable")
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--root",
            str(ROOT),
            "--env-file",
            str(ROOT / "web-dashboard" / ".env.production.example"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["validation"] == "FR06B2_COMPOSE_OVERLAY_PASS"
    assert evidence["compose_profile_scope"] == "*"
    assert evidence["protected_root_count"] == 11
    assert evidence["protected_mount_count"] == 54
    assert evidence["affected_service_definition_count"] == 22
    assert evidence["legacy_protected_mounts_after_merge"] == 0
    assert evidence["unrelated_service_or_top_level_drift"] is False
    assert evidence["docker_daemon_or_service_start_required"] is False
    assert evidence["production_changed"] is False


def test_fr06b2_retained_render_proof_matches_reviewed_sources() -> None:
    proof = _json(PROOF)
    profiles = proof["render_profiles"]
    assert proof["all_checks_passed"] is True
    assert {item["env_profile"] for item in profiles} == {
        ".env.production.example",
        ".env.production",
    }
    expected_hashes = {
        "base_compose_sha256": hashlib.sha256(
            (ROOT / "web-dashboard" / "docker-compose.production.yml").read_bytes()
        ).hexdigest(),
        "overlay_sha256": hashlib.sha256(OVERLAY.read_bytes()).hexdigest(),
        "contract_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        "validator_sha256": hashlib.sha256(VALIDATOR.read_bytes()).hexdigest(),
    }
    for profile in profiles:
        assert profile["validation"] == "FR06B2_COMPOSE_OVERLAY_PASS"
        assert profile["protected_mount_count"] == 54
        assert profile["affected_service_definition_count"] == 22
        for field, expected in expected_hashes.items():
            assert profile[field] == expected
    assert proof["discovery"]["newly_covered_dormant_writer"] == (
        "audio-song-worker-secondary"
    )
    assert proof["cutover_gate"]["production_cutover_allowed_by_this_receipt"] is False


def test_fr06b2_keeps_production_and_parent_gates_closed() -> None:
    contract = _json(CONTRACT)
    boundary = contract["scope_boundary"]
    assert contract["cutover_orchestration"][
        "production_cutover_allowed_by_this_contract"
    ] is False
    for key in (
        "production_compose_applied",
        "external_docker_volumes_created",
        "production_vaults_created",
        "production_keys_created",
        "production_services_stopped_or_restarted",
        "production_volumes_written",
        "deployment_or_cutover_performed",
        "reboot_performed",
        "cloudflare_changed",
        "fr06b_or_fr06_parent_completion_claimed",
    ):
        assert boundary[key] is False
    startup = contract["startup_and_systemd_gate"]
    assert startup["source_unit_shipped_by_fr06b2"] is False
    assert startup["production_boot_acceptance_complete"] is False
    assert "restart: unless-stopped" in startup["reason"]
    assert contract["rollback"][
        "blind_base_compose_reversion_after_new_writes_allowed"
    ] is False
    gates = "\n".join(contract["cutover_orchestration"]["prerequisites"])
    for required in (
        "encrypted R2",
        "outside the unencrypted host root",
        "off-host",
        "out-of-band",
        "writable descriptor",
        "Docker daemon restart",
    ):
        assert required in gates


def test_fr06b2_receipt_does_not_overclaim_live_encryption() -> None:
    receipt = " ".join(RECEIPT.read_text(encoding="utf-8").casefold().split())
    assert "does not create" in receipt
    assert "live cutover remains forbidden" in receipt
    assert "does not claim that production data is encrypted" in receipt
    assert "does not close fr-06b or fr-06" in receipt
    assert "standalone systemd target cannot gate" in receipt
