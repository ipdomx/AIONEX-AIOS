from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def c():return json.loads((ROOT/'docs/project/receipts/FR-06C5E-memory-controls-contract.json').read_text())
def test_source_merge_is_inert():
 s=c()['scope_boundary'];assert s['source_merge_changes_swap'] is False;assert s['source_merge_mounts_tmpfs'] is False;assert s['source_merge_edits_fstab'] is False
def test_new_swap_backing_not_legacy_in_place():
 s=c()['swap'];assert s['encrypted_backing']!='/swap.img';assert s['legacy_plaintext_swap_must_be_inactive_after_apply'];assert s['secure_erase_claimed'] is False
def test_random_key_is_ephemeral_and_unrecoverable():
 s=c()['swap'];assert s['random_key_generated_each_activation'];assert s['random_key_removed_after_mapper_open'];assert s['persistent_recovery_key'] is False
def test_tmpfs_gate_requires_zero_hidden_fds():assert c()['tmp']['hidden_underlay_fd_count_must_be_zero'] is True
def test_memory_reserve_gate():assert c()['activation']['memory_reserve_bytes']==8*1024**3
def test_boot_units():
 assert (ROOT/'deploy/systemd/aionex-fr06c5-encrypted-swap.service').is_file();assert (ROOT/'deploy/systemd/tmp.mount').is_file()
def test_swap_service_calls_boot_commands():
 t=(ROOT/'deploy/systemd/aionex-fr06c5-encrypted-swap.service').read_text();assert 'boot-swap-start' in t and 'boot-swap-stop' in t and 'Conflicts=swap.img.swap' in t
def test_tmp_unit_is_tmpfs_hardened():
 t=(ROOT/'deploy/systemd/tmp.mount').read_text();assert 'What=tmpfs' in t and 'Where=/tmp' in t and 'nodev,nosuid' in t and 'mode=1777' in t
def test_apply_never_claims_secure_erase():
 t=(ROOT/'scripts/security/fr06c5_memory_controls.py').read_text();assert "secure_erase_claimed':False" in t;assert 'shred' not in t
def test_apply_checks_tmp_holders_and_memory():
 t=(ROOT/'scripts/security/fr06c5_memory_controls.py').read_text();assert 'tmp_holders()' in t and 'MemAvailable' in t and 'used+RESERVE' in t
def test_boot_swap_key_is_removed():
 t=(ROOT/'scripts/security/fr06c5_memory_controls.py').read_text();assert "KEY.unlink(missing_ok=True)" in t and "os.urandom(64)" in t
def test_next_subpart():assert c()['next_subpart'].startswith('FR-06C5 closeout')


def test_tmp_holder_gate_is_rechecked_at_mount_boundary():
    text=(ROOT/'scripts/security/fr06c5_memory_controls.py').read_text()
    assert "holders=tmp_holders()" in text and "holders appeared before mount" in text

def test_failed_activation_consumes_fstab_rollback_copy_after_restore():
    text=(ROOT/'scripts/security/fr06c5_memory_controls.py').read_text()
    assert 'FSTAB_BACKUP.unlink()' in text
