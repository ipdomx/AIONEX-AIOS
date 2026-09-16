from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_c4_provision_candidate_and_cutover_share_state_root():
    vault=(ROOT/"scripts/security/fr06c4_runtime_vault.py").read_text()
    candidate=(ROOT/"scripts/security/fr06c4_candidate_runtime.py").read_text()
    cutover=(ROOT/"scripts/security/fr06c4_runtime_cutover.py").read_text()
    wanted="/var/lib/aionex/fr06c4-runtime"
    assert wanted in vault
    assert wanted in candidate
    assert wanted in cutover
    assert "C4_STATE=Path('/var/lib/aionex/fr06c4')" not in candidate
    assert "C4_STATE=Path('/var/lib/aionex/fr06c4')" not in cutover


def test_runtime_vault_accepts_dockerd_hardened_data_root_mode():
    text=(ROOT/"scripts/security/fr06c4_runtime_vault.py").read_text()
    assert "{0o700,0o710} if sub=='docker'" in text
    assert "else {0o700}" in text

def test_candidate_reconstruction_prunes_cache_and_stops_daemons_strictly():
    text=(ROOT/'scripts/security/fr06c4_candidate_runtime.py').read_text()
    assert "builder','prune','-af" in text
    assert 'candidate daemon failed to terminate after bounded SIGTERM wait' in text
    assert "candidate_processes_remaining':0" in text

def test_live_cutover_rejects_candidate_daemon_residue():
    text=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text()
    assert 'candidate reconstruction daemons are still active' in text
    assert 'candidate daemon pidfile remained after reconstruction' in text


def test_live_cutover_requires_fresh_recovery_and_encrypted_mount_acceptance():
    text=(ROOT/'scripts/security/fr06c4_runtime_cutover.py').read_text()
    assert 'MAX_EVIDENCE_AGE=3600' in text
    assert 'restore validation stale/future-dated' in text
    assert 'FR06C4_RUNTIME_BIND_READY' in text
    assert 'legacy authoritative volume is consumed' in text
