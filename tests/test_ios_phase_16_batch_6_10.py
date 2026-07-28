from aios.ios.biometric_grants import IOSBiometricGrantService
from aios.ios.release_manager import IOSRelease, IOSReleaseManager, IOSReleaseStage
from aios.ios.sync_engine import IOSSyncEngine, SyncRecord, SyncState
from aios.ios.telemetry import IOSTelemetryEvent, IOSTelemetryService


def test_ios_sync_detects_and_resolves_conflict() -> None:
    engine = IOSSyncEngine()
    engine.queue(
        SyncRecord(
            record_id="sync-1",
            owner_id="owner-1",
            entity_type="project",
            entity_id="project-1",
            local_version=1,
            remote_version=1,
            payload={"name": "local"},
        )
    )

    conflicted = engine.reconcile("sync-1", "owner-1", remote_version=2)
    assert conflicted.state is SyncState.CONFLICT

    resolved = engine.resolve_conflict("sync-1", "owner-1", merged_payload={"name": "merged"})
    assert resolved.state is SyncState.SYNCED
    assert resolved.local_version == 3


def test_ios_biometric_grant_is_owner_and_device_scoped() -> None:
    service = IOSBiometricGrantService()
    service.issue(
        grant_id="grant-1",
        owner_id="owner-1",
        device_id="device-1",
        scope="payments.approve",
    )

    assert service.authorize("grant-1", "owner-1", "device-1", "payments.approve") is True

    try:
        service.authorize("grant-1", "owner-2", "device-1", "payments.approve")
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-owner biometric access must be rejected")


def test_ios_release_manager_enforces_staged_promotion() -> None:
    manager = IOSReleaseManager()
    manager.create(IOSRelease(release_id="r-1", version="1.0.0", build_number=1))

    manager.promote("r-1", IOSReleaseStage.TESTFLIGHT)
    phased = manager.promote("r-1", IOSReleaseStage.PHASED, rollout_percent=25)
    assert phased.rollout_percent == 25

    production = manager.promote("r-1", IOSReleaseStage.PRODUCTION)
    assert production.rollout_percent == 100


def test_ios_telemetry_is_owner_isolated() -> None:
    service = IOSTelemetryService()
    service.record(
        IOSTelemetryEvent(
            event_id="event-1",
            owner_id="owner-1",
            device_id="device-1",
            name="app.launch",
        )
    )

    assert len(service.list_for_owner("owner-1")) == 1
    assert service.list_for_owner("owner-2") == []
