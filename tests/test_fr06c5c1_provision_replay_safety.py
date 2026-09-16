"""Behavioral regression tests: only disposable paths and fake system commands."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import os

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    spec = spec_from_file_location("fr06c5_provision_safety", ROOT / "scripts/security/fr06c5_host_state_vault.py")
    m = module_from_spec(spec)
    spec.loader.exec_module(m)
    for name, rel in {"IMAGE": "vault/image", "MAPPER": "mapper", "MOUNT": "mount", "STATE": "state", "RUN": "run", "KEYS": "keys"}.items():
        monkeypatch.setattr(m, name, tmp_path / rel)
    monkeypatch.setattr(m, "SIZE", 4096)
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    monkeypatch.setattr(m.os, "chown", lambda *a: None)
    monkeypatch.setattr(m.shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * 1024**3))
    plan = {"plan_id": "a" * 64, "merge_sha": "b" * 40, "active_bundle_sha256": "active", "recovery_bundle_sha256": "recovery"}
    monkeypatch.setattr(m, "loadplan", lambda p: dict(plan))
    monkeypatch.setattr(m, "gitgate", lambda sha: None)
    monkeypatch.setattr(m, "bundle", lambda p, purpose: (b"a" * 64 if purpose == "active" else b"r" * 64, purpose))
    args = SimpleNamespace(plan=tmp_path / "plan.json", merge_sha=plan["merge_sha"], active_bundle=tmp_path / "active", recovery_bundle=tmp_path / "recovery", confirmation="PROVISION-" + plan["plan_id"][:16], confirm_production=m.CONFIRM)
    commands = []
    mounted = {"value": False}
    monkeypatch.setattr(m.os.path, "ismount", lambda p: Path(p) == m.MOUNT and mounted["value"])

    def run(command, timeout=300):
        commands.append(command)
        if command[:2] == ["cryptsetup", "open"]:
            m.MAPPER.write_text("synthetic mapper")
        if command[:2] == ["cryptsetup", "luksHeaderBackup"]:
            Path(command[-1]).write_text("synthetic header")
        return ""

    def mount():
        m.MOUNT.mkdir(exist_ok=True)
        mounted["value"] = True

    def cleanup(command, **kwargs):
        commands.append(command)
        if command[0] == "umount":
            mounted["value"] = False
        if command[:2] == ["cryptsetup", "close"]:
            m.MAPPER.unlink(missing_ok=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(m, "run", run)
    monkeypatch.setattr(m, "mount_vault", mount)
    monkeypatch.setattr(m, "verify_host", lambda: {"validation": "synthetic-ready"})
    monkeypatch.setattr(m.subprocess, "run", cleanup)
    return SimpleNamespace(m=m, args=args, commands=commands, mounted=mounted, run=run)


@pytest.mark.parametrize("boundary", ["image", "dangling_image", "mapper", "mount", "receipt", "header"])
def test_existing_resource_is_rejected_before_commands_and_preserved(sandbox, boundary):
    s = sandbox
    m = s.m
    m.IMAGE.parent.mkdir(parents=True)
    if boundary == "image":
        m.IMAGE.write_bytes(b"existing vault")
    elif boundary == "dangling_image":
        m.IMAGE.symlink_to(m.IMAGE.parent / "missing")
    elif boundary == "mapper":
        m.MAPPER.write_text("existing mapper")
    elif boundary == "mount":
        s.mounted["value"] = True
    elif boundary == "receipt":
        m.STATE.mkdir()
        (m.STATE / "provision-receipt.json").write_text("existing receipt")
    else:
        m.RUN.mkdir()
        (m.RUN / "host-state-vault.header").write_text("existing header")
    with pytest.raises(m.B):
        m.apply(s.args)
    assert s.commands == []
    if boundary == "image":
        assert m.IMAGE.read_bytes() == b"existing vault"
    elif boundary == "dangling_image":
        assert m.IMAGE.is_symlink()
    elif boundary == "mapper":
        assert m.MAPPER.read_text() == "existing mapper"
    elif boundary == "mount":
        assert s.mounted["value"]
    elif boundary == "receipt":
        assert (m.STATE / "provision-receipt.json").read_text() == "existing receipt"
    else:
        assert (m.RUN / "host-state-vault.header").read_text() == "existing header"


def test_successful_plan_cannot_be_replayed(sandbox):
    s = sandbox
    assert s.m.apply(s.args)["status"] == "empty_host_state_vault_provisioned_admission_closed"
    before = s.m.IMAGE.read_bytes()
    s.commands.clear()
    with pytest.raises(s.m.B):
        s.m.apply(s.args)
    assert s.commands == []
    assert s.m.IMAGE.read_bytes() == before
    assert s.m.MAPPER.exists() and s.mounted["value"]
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))


def test_failed_attempt_cannot_reuse_plan_even_after_owned_image_cleanup(sandbox, monkeypatch):
    s = sandbox
    def fail(command, timeout=300):
        s.commands.append(command)
        raise s.m.B("synthetic format failure")
    monkeypatch.setattr(s.m, "run", fail)
    with pytest.raises(s.m.B, match="synthetic"):
        s.m.apply(s.args)
    assert not s.m.IMAGE.exists()
    s.commands.clear()
    with pytest.raises(s.m.B, match="already attempted"):
        s.m.apply(s.args)
    assert s.commands == []
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))


def test_exclusive_create_refuses_target_inserted_after_precheck(sandbox, monkeypatch):
    s = sandbox
    old = s.m.write_exclusive
    def insert_after_check(path, value):
        old(path, value)
        if path.name.startswith("provision-attempt-"):
            s.m.IMAGE.parent.mkdir(parents=True)
            s.m.IMAGE.write_bytes(b"concurrent vault")
    monkeypatch.setattr(s.m, "write_exclusive", insert_after_check)
    with pytest.raises(FileExistsError):
        s.m.apply(s.args)
    assert s.m.IMAGE.read_bytes() == b"concurrent vault"
    assert s.commands == []


def test_cleanup_preserves_replaced_inode(sandbox, monkeypatch):
    s = sandbox
    def replace_and_fail(command, timeout=300):
        s.m.IMAGE.rename(s.m.IMAGE.with_suffix(".owned"))
        s.m.IMAGE.write_bytes(b"replacement vault")
        raise s.m.B("synthetic replacement")
    monkeypatch.setattr(s.m, "run", replace_and_fail)
    with pytest.raises(s.m.B):
        s.m.apply(s.args)
    assert s.m.IMAGE.read_bytes() == b"replacement vault"
    assert s.m.IMAGE.with_suffix(".owned").exists()


def test_failed_teardown_keeps_backing_file_for_reconciliation(sandbox, monkeypatch):
    s = sandbox
    def fail_format(command, timeout=300):
        s.run(command, timeout)
        if command[0] == "mkfs.ext4":
            raise s.m.B("synthetic filesystem failure")
        return ""
    monkeypatch.setattr(s.m, "run", fail_format)
    monkeypatch.setattr(s.m.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(s.m.B):
        s.m.apply(s.args)
    assert s.m.IMAGE.exists()
    assert s.m.MAPPER.exists()
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))


def test_temporary_key_failure_cleans_keys_and_releases_lock(sandbox, monkeypatch):
    s = sandbox
    original = s.m.os.open
    def fail_recovery(path, flags, mode=0o777, **kwargs):
        if Path(path).name == "recovery" and Path(path).parent.name.startswith("apply-"):
            raise OSError("synthetic key write failure")
        return original(path, flags, mode, **kwargs)
    monkeypatch.setattr(s.m.os, "open", fail_recovery)
    with pytest.raises(OSError, match="synthetic"):
        s.m.apply(s.args)
    assert not s.m.IMAGE.exists()
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))
    fd = original(s.m.RUN / "operation.lock", os.O_RDWR)
    try:
        s.m.fcntl.flock(fd, s.m.fcntl.LOCK_EX | s.m.fcntl.LOCK_NB)
    finally:
        os.close(fd)


def test_partial_open_error_preserves_live_mapper_backing_file(sandbox, monkeypatch):
    s = sandbox
    def open_then_fail(command, timeout=300):
        s.run(command, timeout)
        if command[:2] == ["cryptsetup", "open"]:
            raise TimeoutError("synthetic open timeout after mapper creation")
        return ""
    monkeypatch.setattr(s.m, "run", open_then_fail)
    with pytest.raises(TimeoutError):
        s.m.apply(s.args)
    assert s.m.IMAGE.exists()
    assert s.m.MAPPER.exists()
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))


def test_another_operation_lock_rejects_without_claim_or_key_creation(sandbox):
    s = sandbox
    s.m.RUN.mkdir()
    fd = os.open(s.m.RUN / "operation.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        s.m.fcntl.flock(fd, s.m.fcntl.LOCK_EX | s.m.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            s.m.apply(s.args)
        assert s.commands == []
        assert not s.m.KEYS.exists()
        assert not list(s.m.STATE.glob("provision-attempt-*"))
        assert not s.m.IMAGE.exists()
    finally:
        s.m.fcntl.flock(fd, s.m.fcntl.LOCK_UN)
        os.close(fd)
    assert s.m.apply(s.args)["status"] == "empty_host_state_vault_provisioned_admission_closed"


def test_short_key_write_rejects_before_cryptsetup_and_cleans_inputs(sandbox, monkeypatch):
    s = sandbox
    original = s.m.os.write
    def short_write(fd, data):
        if len(data) == 64:
            return original(fd, data[:-1])
        return original(fd, data)
    monkeypatch.setattr(s.m.os, "write", short_write)
    with pytest.raises(s.m.B, match="key write incomplete"):
        s.m.apply(s.args)
    assert s.commands == []
    assert not s.m.IMAGE.exists()
    assert not list(s.m.KEYS.rglob("active"))
    assert not list(s.m.KEYS.rglob("recovery"))
