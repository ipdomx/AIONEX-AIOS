from aios.mobile.android.biometric_security import AndroidBiometricSecurity
from aios.mobile.android.release_manager import AndroidRelease, AndroidReleaseManager, ReleaseChannel
from aios.mobile.android.sync_engine import AndroidSyncEngine, SyncRecord, SyncState
from aios.mobile.android.telemetry import AndroidTelemetryCollector, MobileTelemetryEvent, TelemetryLevel


def test_sync_engine_is_owner_scoped_and_version_aware() -> None:
    engine = AndroidSyncEngine()
    engine.enqueue(SyncRecord("r1", "owner-1", "project", "p1", 1, {"name": "A"}))
    engine.enqueue(SyncRecord("r1", "owner-1", "project", "p1", 1, {"name": "old"}))
    batch = engine.next_batch("owner-1")
    assert len(batch) == 1
    assert batch[0].state is SyncState.SYNCING
    engine.mark_synced("r1", "owner-1")
    assert engine.next_batch("owner-1") == []


def test_biometric_grants_enforce_device_owner() -> None:
    security = AndroidBiometricSecurity(grant_ttl_minutes=5)
    security.grant("device-1", "owner-1")
    security.require("device-1", "owner-1")
    try:
        security.require("device-1", "owner-2")
    except PermissionError:
        pass
    else:
        raise AssertionError("biometric grant must be owner scoped")


def test_release_manager_requires_beta_before_production() -> None:
    manager = AndroidReleaseManager()
    release = manager.publish(
        AndroidRelease(
            version_name="1.0.0",
            version_code=1,
            artifact_sha256="a" * 64,
            channel=ReleaseChannel.INTERNAL,
        )
    )
    try:
        manager.promote(release.version_code, ReleaseChannel.PRODUCTION)
    except RuntimeError:
        pass
    else:
        raise AssertionError("internal release cannot go directly to production")
    beta = manager.promote(release.version_code, ReleaseChannel.BETA)
    production = manager.promote(beta.version_code, ReleaseChannel.PRODUCTION)
    assert production.channel is ReleaseChannel.PRODUCTION


def test_telemetry_deduplicates_and_isolates_owners() -> None:
    collector = AndroidTelemetryCollector(max_events_per_device=2)
    event = MobileTelemetryEvent("e1", "owner-1", "device-1", "sync_failed", TelemetryLevel.ERROR)
    collector.record(event)
    collector.record(event)
    collector.record(MobileTelemetryEvent("e2", "owner-2", "device-2", "opened", TelemetryLevel.INFO))
    assert collector.error_count("owner-1") == 1
    assert len(collector.list_for_owner("owner-1")) == 1
    assert len(collector.list_for_owner("owner-2")) == 1
