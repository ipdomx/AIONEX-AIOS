"""Fail-closed Owner review of historical ambiguous provider submissions."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.owner.identity_media import execution_recovery_review, router
from app.core.auth import require_super_owner
from app.services.identity_media_recovery_triage import (
    owner_identity_media_recovery_snapshot,
    safe_recovery_review_row,
    safe_unverified_failed_row,
)


def record(**fields):
    value = {
        "id": "lab-review-1",
        "operation": "voice_transform",
        "provider": "replicate",
        "status": "needs_review",
        "provider_state": "not_started",
        "attempts": 1,
        "created_at": datetime(2026, 10, 22, 8, 0, tzinfo=UTC),
        "error_code": "provider_submission_ambiguous",
        "provider_job_id": None,
        "secondary_provider_job_id": None,
    }
    value.update(fields)
    return value


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeReadOnlySession:
    def __init__(
        self, total=0, missing=0, rows=(),
        failed_total=0, failed_missing=0, failed_rows=(),
    ):
        self.counts = [total, missing, failed_total, failed_missing]
        self.rows = [rows, failed_rows]
        self.sql = []

    async def scalar(self, statement):
        self.sql.append(str(statement))
        return self.counts.pop(0)

    async def execute(self, statement):
        self.sql.append(str(statement))
        return Result(self.rows.pop(0))


class FR08OwnerReviewTests(unittest.TestCase):
    def test_no_provider_reference_never_invents_billing_truth(self):
        item = safe_recovery_review_row(record())
        self.assertEqual(item["review_kind"], "no_provider_reference_manual_reconciliation")
        self.assertFalse(item["provider_reference_recorded"])
        self.assertFalse(item["automatic_replay_allowed"])
        self.assertFalse(item["actual_provider_charge_verified"])
        self.assertTrue(item["needs_external_provenance_review"])

    def test_raw_provider_data_secrets_and_customer_identifiers_never_appear(self):
        sentinel = "synthetic-confidential-string-not-to-export"
        row = record(
            provider_job_id=sentinel,
            secondary_provider_job_id=sentinel,
            request_payload={"prompt": sentinel},
            input_storage_keys={"source": sentinel},
            output_storage_key=sentinel,
            subject_reference=sentinel,
            rights_evidence_sha256=sentinel,
            lease_token=sentinel,
            idempotency_key=sentinel,
            error_message=sentinel,
        )
        item = safe_recovery_review_row(row)
        self.assertNotIn(sentinel, json.dumps(item))
        self.assertTrue(item["provider_reference_recorded"])
        self.assertEqual(item["review_kind"], "recorded_provider_reference_requires_check")

    def test_only_known_static_error_categories_are_returned(self):
        cases = [
            ("provider_submission_ambiguous", "provider_submission_ambiguous"),
            ("identity_media_worker_error", "identity_media_worker_error"),
            ("provider_job_missing", "provider_job_missing"),
            ("unknown potentially sensitive error value", "unclassified"),
            (None, "unclassified"),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                self.assertEqual(
                    safe_recovery_review_row(record(error_code=error))["error_category"],
                    expected,
                )

    def test_other_status_never_transforms_to_review_status(self):
        with self.assertRaisesRegex(ValueError, "review-required"):
            safe_recovery_review_row(record(status="failed"))

    def test_seven_historical_unknown_provider_references_fail_closed(self):
        rows = [
            record(id=f"lab-id-{i}", error_code=(
                "provider_submission_ambiguous" if i == 0
                else "identity_media_worker_error"
            ))
            for i in range(7)
        ]
        fake = FakeReadOnlySession(7, 7, rows)
        response = asyncio.run(owner_identity_media_recovery_snapshot(fake))
        self.assertEqual(response["total_review_required"], 7)
        self.assertEqual(response["no_provider_reference"], 7)
        self.assertEqual(response["provider_reference_recorded"], 0)
        self.assertEqual(response["shown"], 7)
        self.assertFalse(response["truncated"])
        self.assertFalse(response["automatic_replay_allowed"])
        self.assertFalse(response["actual_provider_charges_verified"])
        self.assertFalse(response["provider_job_ids_returned"])
        self.assertFalse(response["raw_credentials_returned"])
        self.assertFalse(response["customer_identity_or_storage_paths_returned"])
        self.assertTrue(response["read_only"])
        self.assertEqual(len(fake.sql), 6)
        self.assertTrue(all(text.lstrip().upper().startswith("SELECT") for text in fake.sql))
        self.assertTrue(all(x["automatic_replay_allowed"] is False for x in response["executions"]))

    def test_paginated_review_never_misstates_global_counts(self):
        response = asyncio.run(owner_identity_media_recovery_snapshot(
            FakeReadOnlySession(125, 123, [record()]), limit=1,
        ))
        self.assertEqual(response["total_review_required"], 125)
        self.assertEqual(response["no_provider_reference"], 123)
        self.assertEqual(response["provider_reference_recorded"], 2)
        self.assertEqual(response["shown"], 1)
        self.assertTrue(response["truncated"])

    def test_empty_review_after_successful_read(self):
        report = asyncio.run(owner_identity_media_recovery_snapshot(FakeReadOnlySession()))
        self.assertEqual(report["status"], "no_review_records")
        self.assertEqual(report["total_review_required"], 0)
        self.assertTrue(report["read_only"])

    def test_limits_strictly_bounded(self):
        for limit in (-1, 0, 101, 100000):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                    asyncio.run(owner_identity_media_recovery_snapshot(
                        FakeReadOnlySession(), limit=limit,
                    ))

    def test_inconsistent_provider_reference_count_fails(self):
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            asyncio.run(owner_identity_media_recovery_snapshot(FakeReadOnlySession(2, 3)))

    def test_fetched_rows_exceed_global_total_fails(self):
        with self.assertRaisesRegex(ValueError, "exceed total"):
            asyncio.run(owner_identity_media_recovery_snapshot(
                FakeReadOnlySession(0, 0, [record()])
            ))

    def test_failed_started_provider_job_is_visible_without_raw_job_identity(self):
        sentinel = "customer-input-and-secret-must-never-be-returned"
        item = safe_unverified_failed_row(record(
            status="failed",
            provider_state="starting",
            provider_job_id=sentinel,
            error_message=sentinel,
            request_payload={"prompt": sentinel},
            subject_reference=sentinel,
        ))
        self.assertEqual(item["status"], "failed")
        self.assertTrue(item["provider_reference_recorded"])
        self.assertEqual(
            item["review_kind"],
            "failed_provider_state_requires_read_only_reconciliation",
        )
        self.assertFalse(item["automatic_replay_allowed"])
        self.assertFalse(item["actual_provider_charge_verified"])
        self.assertNotIn(sentinel, json.dumps(item))

    def test_failed_without_provider_ref_does_not_imply_no_cost(self):
        item = safe_unverified_failed_row(record(
            status="failed", provider_state="processing", provider_job_id=None
        ))
        self.assertEqual(
            item["review_kind"],
            "failed_no_provider_reference_requires_manual_reconciliation",
        )
        self.assertFalse(item["actual_provider_charge_verified"])
        self.assertTrue(item["needs_external_provenance_review"])

    def test_ineligible_failed_or_successful_provider_state_rejected(self):
        for status, state in (
            ("completed", "succeeded"),
            ("needs_review", "not_started"),
            ("failed", "succeeded"),
            ("failed", "not_started"),
        ):
            with self.subTest(status=status, state=state):
                with self.assertRaisesRegex(ValueError, "unverified failed"):
                    safe_unverified_failed_row(record(
                        status=status, provider_state=state
                    ))

    def test_both_review_and_failed_state_are_counted_and_read_only(self):
        failures = [
            record(
                id="failed-1", status="failed", provider_state="starting",
                provider_job_id="remote-job-example-1",
            ),
            record(
                id="failed-2", status="failed", provider_state="processing",
                provider_job_id="remote-job-example-2",
            ),
        ]
        fake = FakeReadOnlySession(
            total=7, missing=7,
            rows=[record(id=f"review-{i}") for i in range(7)],
            failed_total=2, failed_missing=0, failed_rows=failures,
        )
        report = asyncio.run(owner_identity_media_recovery_snapshot(fake))
        self.assertEqual(report["total_review_required"], 7)
        self.assertEqual(report["failed_provider_state_unverified"], 2)
        self.assertEqual(report["failed_no_provider_reference"], 0)
        self.assertEqual(report["failed_provider_reference_recorded"], 2)
        self.assertEqual(len(report["failed_provider_state_executions"]), 2)
        self.assertEqual(len(fake.sql), 6)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in fake.sql))
        self.assertFalse(report["automatic_replay_allowed"])
        self.assertFalse(report["actual_provider_charges_verified"])
        self.assertNotIn("remote-job-example", json.dumps(report))

    def test_failed_counts_and_items_are_consistent(self):
        fake = FakeReadOnlySession(
            total=1, missing=0, rows=[record()],
            failed_total=1, failed_missing=2, failed_rows=[],
        )
        with self.assertRaisesRegex(ValueError, "failed provider state count"):
            asyncio.run(owner_identity_media_recovery_snapshot(fake))

    def test_failed_state_pagination_reports_unobserved_records(self):
        fake = FakeReadOnlySession(
            total=0, missing=0, rows=[],
            failed_total=4, failed_missing=4, failed_rows=[
                record(status="failed",provider_state="starting")
            ],
        )
        report = asyncio.run(owner_identity_media_recovery_snapshot(fake, limit=1))
        self.assertEqual(report["status"], "review_required")
        self.assertTrue(report["failed_provider_state_truncated"])
        self.assertEqual(report["failed_no_provider_reference"], 4)
        self.assertEqual(report["failed_provider_state_shown"], 1)

    def test_route_only_exposes_get_behind_super_owner_dependency(self):
        selected = [
            route for route in router.routes
            if getattr(route, "path", "").endswith("/executions/recovery-review")
        ]
        self.assertEqual(len(selected), 1)
        route = selected[0]
        self.assertEqual(route.methods, {"GET"})
        self.assertIs(route.endpoint, execution_recovery_review)
        self.assertIn(require_super_owner, {
            entry.call for entry in route.dependant.dependencies
        })

    def test_unauthenticated_http_call_rejected(self):
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get("/owner/identity-media/executions/recovery-review")
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn("executions", response.text)


if __name__ == "__main__":
    unittest.main()
