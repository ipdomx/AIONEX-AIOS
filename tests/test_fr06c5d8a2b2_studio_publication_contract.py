"""Source boundaries for local no-replace Studio publication, not host drain."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"
PUBLICATION = SERVICES / "studio_artifact_publication.py"


def function(filename, name):
    tree = ast.parse((SERVICES / filename).read_text())
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def calls(node, name):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call) and ((isinstance(item.func, ast.Name) and item.func.id == name) or (isinstance(item.func, ast.Attribute) and item.func.attr == name))]


def test_existing_store_api_delegates_to_verified_no_replace_publisher():
    node = function("production_studio.py", "store_artifact")
    assert len(calls(node, "publish_studio_archive")) == 1
    assert not calls(node, "replace") and not calls(node, "write_bytes")
    assert not calls(node, "resolve") and not calls(node, "protected_root")
    keywords = {item.arg for item in calls(node, "publish_studio_archive")[0].keywords}
    assert {"checksum", "size_bytes", "maximum_bytes", "content", "root"} <= keywords


def test_publication_uses_exactly_one_descriptor_relative_nofollow_link():
    node = function("studio_artifact_publication.py", "publish_studio_archive")
    links = calls(node, "link")
    assert len(links) == 1
    keywords = {item.arg: item.value for item in links[0].keywords}
    assert {"src_dir_fd", "dst_dir_fd", "follow_symlinks"} == set(keywords)
    assert isinstance(keywords["follow_symlinks"], ast.Constant) and keywords["follow_symlinks"].value is False
    assert not calls(node, "replace") and not calls(node, "rename")
    assert not calls(node, "exists") and not calls(node, "resolve")


def test_only_staging_cleanup_unlinks_and_propagates_errors():
    tree = ast.parse(PUBLICATION.read_text())
    unlink_owners = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and calls(node, "unlink")]
    assert unlink_owners == ["_remove_staging"]
    node = function("studio_artifact_publication.py", "_remove_staging")
    assert not any(isinstance(item, ast.Try) for item in ast.walk(node))
    assert calls(node, "fstat") and calls(node, "stat") and calls(node, "fsync")


def test_no_directory_walking_uses_symlink_resolution_or_shell():
    tree = ast.parse(PUBLICATION.read_text())
    assert not calls(tree, "resolve") and not calls(tree, "system") and not calls(tree, "rmtree")
    source = PUBLICATION.read_text()
    assert "os.O_NOFOLLOW" in source and "os.O_EXCL" in source and "os.O_CLOEXEC" in source
    assert "same-UID/root" in source


def test_publication_has_no_database_or_provider_claims():
    tree = ast.parse(PUBLICATION.read_text())
    imports = [item.module or "" for item in ast.walk(tree) if isinstance(item, ast.ImportFrom)]
    assert not any(item.startswith(("app.db", "sqlalchemy", "httpx", "requests")) for item in imports)
    source = PUBLICATION.read_text()
    assert "not durable execution-resource ownership" in source
    assert "a final name is never deleted" in source


def test_flush_checksum_and_identity_checks_remain_part_of_acceptance():
    node = function("studio_artifact_publication.py", "publish_studio_archive")
    for name in ("fsync", "_verify_bytes", "_assert_file", "_assert_tree", "_remove_staging"):
        assert calls(node, name)
