import importlib.util
import json
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fr04d_asset_preflight.py"

spec = importlib.util.spec_from_file_location("fr04d_asset_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules["fr04d_asset_preflight"] = module
spec.loader.exec_module(module)


def _private_dir(path: Path, *, mode: int = 0o700, uid: int | None = None, gid: int | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    if uid is not None and gid is not None:
        try:
            os.chown(path, uid, gid)
        except PermissionError:
            pass
    return path


def _private_file(path: Path, payload: bytes, *, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.chmod(path, mode)
    return path


def test_fr04d1_preflight_counts_metadata_without_hashing(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "root")
    nested = _private_dir(root / "nested")
    _private_file(nested / "asset.bin", b"abc")

    policy = module.RootPolicy("example", root, owner_uid=os.getuid(), group_gid=os.getgid())
    result = module.preflight((policy,))

    assert result["status"] == "pass"
    assert result["content_read"] is False
    assert result["hashes_computed"] is False
    assert result["totals"]["file_count"] == 1
    assert result["totals"]["directory_count"] == 2
    assert result["totals"]["payload_bytes"] == 3


def test_fr04d1_preflight_rejects_symlink_special_hardlink_and_public_file(tmp_path: Path) -> None:
    root = _private_dir(tmp_path / "root")
    good = _private_file(root / "good.bin", b"good")
    os.link(good, root / "hardlink.bin")
    (root / "link.bin").symlink_to(good)
    public = _private_file(root / "public.bin", b"bad")
    os.chmod(public, 0o644)

    policy = module.RootPolicy("example", root, owner_uid=os.getuid(), group_gid=os.getgid())
    result = module.preflight((policy,))

    assert result["status"] == "fail"
    totals = result["totals"]
    assert totals["symlink_count"] == 1
    assert totals["hardlinked_file_count"] == 2
    assert totals["unsafe_permission_count"] == 1


def test_fr04d1_default_roots_cover_fr04b_without_cache_socket_or_redis() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for root_id in [
        "three_d_asset_data",
        "project_execution_data",
        "course_package_data",
        "media_asset_data",
        "studio_asset_data",
        "portal_asset_data",
        "mobile_release_data",
        "realtime_recording_data",
        "audio_song_ingress_data",
        "security_source_data",
        "security_remediation_data",
    ]:
        assert root_id in source
    forbidden = ["redis_data", "project_npm_cache_data", "security_tool_cache_data", "ollama_model_data", "postgres_socket"]
    for root_id in forbidden:
        assert root_id not in source


def test_fr04d1_cli_uses_json_root_policy(tmp_path: Path, capsys) -> None:
    root = _private_dir(tmp_path / "root")
    _private_file(root / "asset.bin", b"payload")
    roots = tmp_path / "roots.json"
    roots.write_text(
        json.dumps([
            {
                "root_id": "example",
                "path": str(root),
                "directory_mode": "0700",
                "file_mode": "0600",
                "owner_uid": os.getuid(),
                "group_gid": os.getgid(),
            }
        ]),
        encoding="utf-8",
    )

    assert module.main(["--roots-json", str(roots)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["root_count"] == 1
