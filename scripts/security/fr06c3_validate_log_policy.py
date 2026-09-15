#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

class PolicyError(RuntimeError): pass

def validate(root: Path) -> dict:
    root=root.resolve()
    mount=root/'deploy/systemd/var-log.mount'
    journal=root/'deploy/systemd/journald.conf.d/30-aionex-fr06-volatile.conf'
    contract=root/'docs/project/receipts/FR-06C3C6-volatile-log-policy.json'
    for p in (mount,journal,contract):
        if not p.is_file(): raise PolicyError(f'missing source: {p}')
    m=mount.read_text(); j=journal.read_text(); c=json.loads(contract.read_text())
    required_mount=(
        'What=tmpfs','Where=/var/log','Type=tmpfs',
        'Options=mode=0755,nodev,nosuid,noexec,size=1G',
        'Before=local-fs.target systemd-journald.service rsyslog.service',
        'WantedBy=local-fs.target',
    )
    if any(x not in m for x in required_mount): raise PolicyError('var-log.mount contract drifted')
    for x in ('Storage=volatile','RuntimeMaxUse=512M','RuntimeMaxFileSize=64M'):
        if x not in j: raise PolicyError('journald volatile contract drifted')
    if c.get('subpart')!='FR-06C3C6': raise PolicyError('contract identity drifted')
    if c['selected_policy']['var_log_filesystem']!='tmpfs': raise PolicyError('log filesystem policy drifted')
    if c['production_activation_gate']['source_merge_installs_policy'] is not False: raise PolicyError('source merge must not activate policy')
    if c['scope_boundary']['production_systemd_changed_by_source_merge'] is not False: raise PolicyError('scope boundary drifted')
    return {'schema_version':1,'subpart':'FR-06C3C6','validation':'FR06C3_VOLATILE_LOG_POLICY_PASS','production_changed':False,'var_log_filesystem':'tmpfs','journald_storage':'volatile'}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]); a=p.parse_args()
    try: print(json.dumps(validate(a.root),sort_keys=True)); return 0
    except (PolicyError,OSError,ValueError) as e: print(json.dumps({'status':'blocked','reason':str(e)},sort_keys=True)); return 2
if __name__=='__main__': raise SystemExit(main())
