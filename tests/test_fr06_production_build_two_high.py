"""Production build regressions and exact Grype migration guards; no live actions."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'web-dashboard/backend/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('grype_two_high_contract', SCRIPTS / 'build_grype.py')
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.pop(0)


@pytest.fixture
def migration(tmp_path):
    folder = tmp_path / 'lock'
    folder.mkdir()
    real = ROOT / 'web-dashboard/backend/security-build/grype'
    shutil.copytree(real / 'patches', folder / 'patches')
    lock = json.loads((real / 'lock.json').read_text())
    source = tmp_path / 'source'
    source.mkdir()
    for name in ('go.mod', 'go.sum'):
        (source / name).write_text('pristine module data\n')
        lock['upstream_files'][name] = m.sha(source / name)
        (folder / name).write_text('migrated module data\n')
        lock['files'][name] = m.sha(folder / name)
    for target, entry in lock['source_patches'].items():
        p = source / target
        p.parent.mkdir(parents=True, exist_ok=True)
        if entry['before_sha256'] is not None:
            p.write_text('pristine source for ' + target + '\n')
            entry['before_sha256'] = m.sha(p)
    (folder / 'lock.json').write_text(json.dumps(lock))
    return source, folder, lock


def state(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def test_exact_migration_applies_code_and_module_graph(migration):
    source, folder, lock = migration
    m.apply_source_patches(source, folder, lock)
    for path, entry in lock['source_patches'].items():
        assert m.sha(source / path) == entry['after_sha256']
    for name, digest in lock['files'].items():
        assert m.sha(source / name) == digest
    before = state(source)
    with pytest.raises(ValueError):
        m.apply_source_patches(source, folder, lock)
    assert state(source) == before


@pytest.mark.parametrize('target', list(m.PATCH_TARGETS))
@pytest.mark.parametrize('fault', ['source-drift', 'replacement-drift', 'replacement-symlink', 'source-symlink'])
def test_migration_drift_refused_before_any_write(migration, target, fault):
    source, folder, lock = migration
    entry = lock['source_patches'][target]
    p = source / target
    replacement = folder / 'patches' / entry['replacement']
    if fault == 'source-drift':
        p.write_text('unexpected source or pre-existing regression')
    elif fault == 'replacement-drift':
        replacement.write_text('unreviewed replacement')
    elif fault == 'replacement-symlink':
        other = replacement.with_suffix('.original')
        replacement.rename(other)
        replacement.symlink_to(other)
    else:
        if p.exists():
            p.unlink()
        p.symlink_to(replacement)
    before = state(source)
    with pytest.raises(ValueError):
        m.apply_source_patches(source, folder, lock)
    assert state(source) == before


@pytest.mark.parametrize('fault', ['missing-set','extra-target','path-escape','missing-old-hash','new-file-old-hash','missing-module-hash','changed-module','wrong-after-hash'])
def test_incomplete_migration_contract_is_not_accepted(migration, fault):
    source, folder, lock = migration
    target = 'cmd/grype/cli/commands/completion.go'
    if fault == 'missing-set':
        del lock['source_patches'][target]
    elif fault == 'extra-target':
        lock['source_patches']['../outside'] = dict(lock['source_patches'][target])
    elif fault == 'path-escape':
        lock['source_patches'][target]['replacement'] = '../../outside'
    elif fault == 'missing-old-hash':
        lock['source_patches'][target]['before_sha256'] = None
    elif fault == 'new-file-old-hash':
        lock['source_patches']['cmd/grype/cli/commands/completion_aios_test.go']['before_sha256'] = 'a' * 64
    elif fault == 'missing-module-hash':
        del lock['upstream_files']['go.sum']
    elif fault == 'changed-module':
        (source / 'go.mod').write_text('unexpected upstream')
    else:
        lock['source_patches'][target]['after_sha256'] = 'a' * 64
    before = state(source)
    with pytest.raises(ValueError):
        m.apply_source_patches(source, folder, lock)
    assert state(source) == before


@pytest.mark.parametrize('dockerfile', ['web-dashboard/frontend/Dockerfile','vip-frontend/Dockerfile'])
def test_retired_tls_revision_replaced_by_checked_security_floor(dockerfile):
    text = (ROOT / dockerfile).read_text()
    assert 'libcrypto3=3.5.8-r0' not in text and 'libssl3=3.5.8-r0' not in text
    assert "'libcrypto3>=3.5.9-r0' 'libssl3>=3.5.9-r0'" in text
    assert 'test "${crypto#libcrypto3-}" = "${ssl#libssl3-}"' in text
    assert 'apk version -t "${crypto#libcrypto3-}" 3.5.9-r0' in text
    assert 'tls-packages.txt' in text and 'USER nextjs' in text
    assert 'apk upgrade --no-cache' in text
    assert '--allow-untrusted' not in text and '--force-broken-world' not in text
    assert '--no-check-certificate' not in text
    assert 'sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf' in text


def test_module_really_removed_without_losing_completion():
    folder = ROOT / 'web-dashboard/backend/security-build/grype'
    for name in ('go.mod','go.sum'):
        assert not any(line.strip().startswith('github.com/docker/docker ') for line in (folder / name).read_text().splitlines())
    migrated = (folder / 'patches/completion.go').read_text()
    assert 'github.com/moby/moby/client' in migrated
    assert 'client.New(client.FromEnv)' in migrated
    assert 'cli.ImageList' in migrated and 'images.Items' in migrated
    assert 'Filters: client.Filters{}.Add("dangling", "false")' in migrated
    assert 'strings.HasPrefix(tag, prefix)' in migrated and 'defer cli.Close()' in migrated
    assert 'cobra.ShellCompDirectiveDefault' in migrated
    assert 'github.com/docker/docker' not in migrated
    regression = (folder / 'patches/completion_aios_test.go').read_text()
    assert 'httptest.NewServer' in regression and 'TestAIOSCompletionUnavailablePreservesShellFallback' in regression
    builder = (SCRIPTS / 'build_grype.py').read_text()
    assert 'Obsolete Docker module still present' in builder and 'Obsolete Docker code linked' in builder
    assert 'completion-tests.jsonl' in builder


def test_verifier_still_checks_affected_fixed_and_database_integrity():
    text = (SCRIPTS / 'verify_security_grype.py').read_text()
    assert '0.119.0+aios.2' in text
    assert 'GRYPE_DB_VALIDATE_BY_HASH_ON_START="true"' in text
    assert 'GRYPE_DB_VALIDATE_AGE="true"' in text
    assert '"affected", "1.2.5", True' in text
    assert '"fixed", "1.3.5", False' in text
    assert 'checksum_validation_failure_rejected' in text
