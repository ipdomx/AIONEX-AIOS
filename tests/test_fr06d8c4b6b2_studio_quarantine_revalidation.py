"""FR-06D8C4B6B2 read-only Studio quarantine revalidation acceptance."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_quarantine_revalidation.py"
B5_TEST = ROOT / "tests/test_fr06d8c4b5_studio_staging_quarantine.py"

_spec = importlib.util.spec_from_file_location("fr06d8c4_b6b2", SCRIPT)
assert _spec is not None and _spec.loader is not None
b6b2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b6b2)

_b5_spec = importlib.util.spec_from_file_location(
    "fr06d8c4_b5_fixture_for_b6b2", B5_TEST
)
assert _b5_spec is not None and _b5_spec.loader is not None
b5test = importlib.util.module_from_spec(_b5_spec)
_b5_spec.loader.exec_module(b5test)

CONTAINMENT_ID = "88888888-8888-4888-8888-888888888888"
ORGANIZATION_ID = "99999999-9999-4999-8999-999999999999"
WORKER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RECONCILIATION_OPERATION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _terminal_case(tmp_path: Path, *, layout="owned_staging_present"):
    case = b5test._case(tmp_path, layout=layout)
    volume, staging, cleanup, proc, *_rest = case
    b5_receipt = b5test._evaluate(case)
    quarantine_path = (
        staging.parent
        / b5test.b5._quarantine_name(cleanup["candidate_sha256"])
    )
    assert not staging.exists()
    assert quarantine_path.exists()

    authority = {
        "schema_version": 20,
        "scope": "studio_job_requests",
        "generation": b5_receipt["generation"] + 2,
        "status": "closed",
        "enabled": False,
        "operation_id": RECONCILIATION_OPERATION,
        "reason": "B6B2 fixture closed authority",
        "changed_at": "2026-09-20T02:00:00+00:00",
        "full_host_closure": False,
    }
    value = {
        "schema": b6b2.CANDIDATE_SCHEMA,
        "containment_id": CONTAINMENT_ID,
        "containment_proof_sha256": "1" * 64,
        "observation_id": cleanup["observation_id"],
        "observation_proof_sha256": cleanup["observation_proof_sha256"],
        "execution_id": cleanup["execution_id"],
        "publication_id": cleanup["publication_id"],
        "job_id": cleanup["job_id"],
        "organization_id": ORGANIZATION_ID,
        "worker_incarnation": WORKER_ID,
        "admitted_generation": 20,
        "containment_operation_id": b5_receipt["operation_id"],
        "containment_generation": b5_receipt["generation"],
        "containment_boot_id": b5_receipt["boot_id"],
        "cleanup_candidate_sha256": cleanup["candidate_sha256"],
        "process_scan_receipt_sha256": b5_receipt[
            "process_scan_receipt_sha256"
        ],
        "staging_quarantine_receipt_sha256": b5_receipt[
            "receipt_sha256"
        ],
        "layout": cleanup["layout"],
        "relative_components": deepcopy(cleanup["relative_components"]),
        "original_staging_name": cleanup["staging_name"],
        "final_name": cleanup["final_name"],
        "final_evidence": deepcopy(cleanup["final"]),
        "archive_size_bytes": quarantine_path.stat().st_size,
        "archive_checksum_sha256": hashlib.sha256(
            quarantine_path.read_bytes()
        ).hexdigest(),
        "quarantine_name": b5_receipt["quarantine_name"],
        "retained_identity": deepcopy(b5_receipt["retained_identity"]),
        "reconciliation_authority": authority,
        "reconciliation_authority_sha256": b6b2.scan._sha(authority),
        "host_revalidation_required": True,
        "quarantine_revalidation_required": True,
        "terminalization_authorized": False,
        "blocker_cleared": False,
        "retry_authorized": False,
        "filesystem_cleanup_claimed": False,
        "cleanup_authorized": False,
        "settlement_authorized": False,
        "quarantine_deletion_permitted": False,
        "final_deletion_permitted": False,
        "full_host_closure": False,
    }
    value["candidate_sha256"] = b6b2.scan._sha(value)
    return case, value, quarantine_path


def _provider(volume: Path):
    calls = {"count": 0}

    def current():
        calls["count"] += 1
        return deepcopy(b5test._containers(volume))

    return calls, current


@pytest.mark.parametrize("boot_id", ["boot-123", "boot-after-reboot"])
def test_revalidation_is_read_only_and_allows_fresh_cross_boot_proof(
    tmp_path, boot_id
):
    case, candidate, quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    before = quarantine_path.read_bytes()
    calls, provider = _provider(volume)

    receipt = b6b2.evaluate(
        terminal_candidate=candidate,
        container_provider=provider,
        proc_root=proc,
        boot_id=boot_id,
    )

    assert calls["count"] == 2
    assert quarantine_path.read_bytes() == before
    assert receipt["terminal_candidate_sha256"] == candidate[
        "candidate_sha256"
    ]
    assert receipt["studio_volume_source"] == str(volume)
    assert receipt["container_inventory_sha256"] == b6b2.scan._sha(
        receipt["container_inventory"]
    )
    assert {row["service"] for row in receipt["container_inventory"]} == {
        "backend",
        "studio-worker",
        "backup-worker",
    }
    assert receipt["retained_identity"] == candidate["retained_identity"]
    assert receipt["archive_size_bytes"] == candidate["archive_size_bytes"]
    assert receipt["archive_checksum_sha256"] == candidate["archive_checksum_sha256"]
    assert receipt["content_hash_passes"] == 2
    assert receipt["archive_content_revalidated"] is True
    assert receipt["scan_passes"] == 2
    assert receipt["visible_reference_count"] == 0
    assert receipt["current_container_epoch_stable"] is True
    assert receipt["staging_name_absent"] is True
    assert receipt["quarantine_identity_revalidated"] is True
    assert receipt["final_layout_revalidated"] is True
    assert receipt["quarantine_reference_drain_verified"] is True
    assert receipt["host_process_scan_verified"] is True
    assert receipt["process_drain_verified"] is False
    assert receipt["authority_revalidation_required_by_next_stage"] is True
    assert receipt["terminalization_authorized"] is False
    assert receipt["blocker_cleared"] is False
    assert receipt["retry_authorized"] is False
    assert receipt["filesystem_mutation_performed"] is False
    assert receipt["cleanup_authorized"] is False
    assert receipt["settlement_authorized"] is False
    assert receipt["quarantine_deletion_permitted"] is False
    assert receipt["final_deletion_permitted"] is False
    assert receipt["full_host_closure"] is False
    assert receipt["same_boot_as_containment"] is (
        boot_id == candidate["containment_boot_id"]
    )


def test_visible_quarantine_reference_blocks(tmp_path):
    case, candidate, quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    link = proc / "100" / "task" / "100" / "fd" / "9"
    link.symlink_to(quarantine_path)
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="still has process references",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_staging_name_reappearance_blocks(tmp_path):
    case, candidate, quarantine_path = _terminal_case(tmp_path)
    volume, staging, _cleanup, proc, *_ = case
    os.link(quarantine_path, staging)
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="staging name reappeared",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_same_inode_same_size_content_replacement_blocks(tmp_path):
    case, candidate, quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    before = quarantine_path.stat()
    replacement = b"foreign replacement"
    assert len(replacement) == before.st_size
    quarantine_path.write_bytes(replacement)
    after = quarantine_path.stat()
    assert after.st_ino == before.st_ino
    assert after.st_size == before.st_size
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="checksum differs",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_final_hardlink_loss_blocks(tmp_path):
    case, candidate, _quarantine_path = _terminal_case(
        tmp_path, layout="owned_staging_and_final_hardlinks"
    )
    volume, staging, cleanup, proc, *_ = case
    final = staging.parent / cleanup["final_name"]
    final.unlink()
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="quarantine identity changed|final hardlink layout changed",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_container_epoch_drift_between_fresh_inventories_blocks(tmp_path):
    case, candidate, _quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        rows = deepcopy(b5test._containers(volume))
        if calls == 2:
            rows[0]["RestartCount"] = 1
            rows[0]["State"]["StartedAt"] = "2026-09-20T02:01:00+00:00"
        return rows

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="container epoch changed",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )
    assert calls == 2


def test_alternate_access_path_to_same_volume_blocks(tmp_path):
    case, candidate, _quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case

    def provider():
        rows = deepcopy(b5test._containers(volume))
        rows[3]["Mounts"].append(
            {
                "Destination": "/unexpected-studio-view",
                "Source": str(volume),
                "RW": False,
                "Type": "bind",
                "Name": None,
            }
        )
        return rows

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="alternate Studio volume access path",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_tampered_candidate_digest_fails_closed(tmp_path):
    case, candidate, _quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    candidate["blocker_cleared"] = True
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="candidate digest differs",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )


def test_open_authority_candidate_is_rejected_even_with_valid_digest(tmp_path):
    case, candidate, _quarantine_path = _terminal_case(tmp_path)
    volume, _staging, _cleanup, proc, *_ = case
    authority = candidate["reconciliation_authority"]
    authority["status"] = "open"
    authority["enabled"] = True
    candidate["reconciliation_authority_sha256"] = b6b2.scan._sha(authority)
    candidate["candidate_sha256"] = b6b2.scan._sha(
        {
            key: item
            for key, item in candidate.items()
            if key != "candidate_sha256"
        }
    )
    _calls, provider = _provider(volume)

    with pytest.raises(
        b6b2.QuarantineRevalidationBlocked,
        match="authority is invalid",
    ):
        b6b2.evaluate(
            terminal_candidate=candidate,
            container_provider=provider,
            proc_root=proc,
            boot_id="boot-current",
        )
