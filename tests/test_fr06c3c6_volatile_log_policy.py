from pathlib import Path
import importlib.util, json
ROOT=Path(__file__).resolve().parents[1]

def _module():
    p=ROOT/'scripts/security/fr06c3_validate_log_policy.py'; s=importlib.util.spec_from_file_location('fr06c3_log_policy',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def test_log_policy_source_validates_without_mutation():
    r=_module().validate(ROOT); assert r['validation']=='FR06C3_VOLATILE_LOG_POLICY_PASS'; assert r['production_changed'] is False

def test_var_log_is_tmpfs_and_boot_ordered():
    t=(ROOT/'deploy/systemd/var-log.mount').read_text(); assert 'What=tmpfs' in t; assert 'Where=/var/log' in t; assert 'nodev,nosuid,noexec' in t; assert 'Before=local-fs.target systemd-journald.service rsyslog.service' in t

def test_journald_is_explicitly_volatile():
    t=(ROOT/'deploy/systemd/journald.conf.d/30-aionex-fr06-volatile.conf').read_text(); assert 'Storage=volatile' in t; assert 'RuntimeMaxUse=512M' in t

def test_source_merge_does_not_activate_live_policy():
    c=json.loads((ROOT/'docs/project/receipts/FR-06C3C6-volatile-log-policy.json').read_text()); assert c['production_activation_gate']['source_merge_installs_policy'] is False; assert c['scope_boundary']['production_systemd_changed_by_source_merge'] is False

def test_residual_plaintext_is_not_misrepresented_as_secure_erasure():
    c=json.loads((ROOT/'docs/project/receipts/FR-06C3C6-volatile-log-policy.json').read_text()); assert c['production_activation_gate']['plaintext_underlay_is_residual_remanence_not_active_storage'] is True


def test_log_policy_accepts_current_host_ready_validation_name() -> None:
    text = (ROOT / 'scripts/security/fr06c3_log_policy.py').read_text(encoding='utf-8')
    assert "FR06C3_VAULTS_HOST_READY" in text
    assert "FR06C3_HOST_VAULTS_READY" in text
