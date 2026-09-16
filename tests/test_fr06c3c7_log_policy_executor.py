from pathlib import Path
import importlib.util, json, argparse
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/security/fr06c3_log_policy.py'
CONTRACT=ROOT/'docs/project/receipts/FR-06C3C7-log-policy-executor.json'

def _module():
    s=importlib.util.spec_from_file_location('fr06c3_log_exec',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_contract_is_source_only_and_fail_closed():
    c=json.loads(CONTRACT.read_text());assert c['subpart']=='FR-06C3C7';assert c['executor']['source_merge_changes_systemd'] is False;assert c['scope_boundary']['source_merge_applies_policy'] is False

def test_executor_has_plan_apply_and_rollback_confirmations():
    m=_module();p=m.parser();assert p.parse_args(['inspect-runtime']).command=='inspect-runtime';assert m.APPLY_CONFIRMATION=='FR06C3_PRODUCTION_VOLATILE_LOG_CUTOVER';assert m.ROLLBACK_CONFIRMATION=='FR06C3_PRODUCTION_VOLATILE_LOG_ROLLBACK'

def test_repository_policy_hashes_and_contents_are_bound(monkeypatch):
    m=_module();monkeypatch.setattr(m,'PRODUCTION_ROOT',ROOT);monkeypatch.setattr(m,'SOURCE_MOUNT',ROOT/'deploy/systemd/var-log.mount');monkeypatch.setattr(m,'SOURCE_JOURNAL',ROOT/'deploy/systemd/journald.conf.d/30-aionex-fr06-volatile.conf');r=m._source_policy();assert len(r['mount_sha256'])==64;assert len(r['journal_sha256'])==64

def test_remove_if_exact_never_deletes_drifted_file(tmp_path):
    m=_module();p=tmp_path/'x';p.write_text('expected');wanted=m._sha(p);p.write_text('drifted');m._remove_if_exact(p,wanted);assert p.exists()

def test_remove_if_exact_deletes_only_exact_file(tmp_path):
    m=_module();p=tmp_path/'x';p.write_text('expected');wanted=m._sha(p);m._remove_if_exact(p,wanted);assert not p.exists()

def test_success_receipt_never_claims_secure_erase():
    c=json.loads(CONTRACT.read_text());assert c['rollback']['secure_erase_claimed'] is False;assert c['rollback']['deletes_historical_log_underlay'] is False


def test_executor_covers_direct_log_fd_holders_and_hidden_underlay():
    c=json.loads(CONTRACT.read_text())
    assert c['executor']['direct_log_services']==['rsyslog.service','fail2ban.service','unattended-upgrades.service']
    assert c['executor']['unknown_direct_log_holder_behavior']=='fail_closed'
    assert c['executor']['hidden_plaintext_underlay_fd_acceptance']==0
    text=SCRIPT.read_text()
    assert "ALLOWED_PRECUTOVER_LOG_HOLDER_COMMS" in text
    assert "_hidden_underlay_holders" in text
    assert "unknown direct /var/log holder" in text
    assert "plaintext /var/log underlay still has open file descriptors" in text
    assert "fail2ban.service" in text and "unattended-upgrades.service" in text

def test_apply_mounts_tmpfs_before_journald_restart():
    text=SCRIPT.read_text()
    start=text.index("for service in DIRECT_LOG_SERVICES:_run(['systemctl','stop',service])")
    mount=text.index("_run(['systemctl','start','var-log.mount'])",start)
    journal=text.index("_run(['systemctl','restart','systemd-journald.service'])",start)
    assert mount < journal
