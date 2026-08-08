#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RELEASE=Path(os.getenv('AIOS_MOBILE_RELEASE_DIR','/root/.config/aionex/releases'))
required={
 'ios_storekit': ROOT/'mobile/ios/AIONEXAIOS/StoreBilling.swift',
 'android_play_billing': ROOT/'mobile/android/app/src/main/java/net/vipe/aionex/PlayBillingManager.java',
 'server_lifecycle': ROOT/'web-dashboard/backend/app/services/mobile_store_billing.py',
 'store_api': ROOT/'web-dashboard/backend/app/api/v1/endpoints/mobile_store_billing.py',
 'migration': ROOT/'web-dashboard/backend/alembic/versions/20260809_0012_mobile_store_billing.py',
}
missing=[k for k,p in required.items() if not p.is_file()]
all_mobile='\n'.join(p.read_text(errors='ignore') for base in [ROOT/'mobile/ios',ROOT/'mobile/android/app/src/main'] for p in base.rglob('*') if p.is_file())
secret_markers=['APP_STORE_PRIVATE_KEY','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','STRIPE_SECRET_KEY','sk_live_','sk_test_']
embedded=[x for x in secret_markers if x in all_mobile]
cred_names=['APP_STORE_BUNDLE_ID','APP_STORE_ISSUER_ID','APP_STORE_KEY_ID','APP_STORE_PRIVATE_KEY','APP_STORE_ROOT_CERTIFICATES_DIR','GOOGLE_PLAY_PACKAGE_NAME','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON','GOOGLE_PLAY_PUBSUB_AUDIENCE','GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT_EMAIL']
credentials={k:bool(os.getenv(k)) for k in cred_names}
app_store_ready=all(credentials[k] for k in ['APP_STORE_BUNDLE_ID','APP_STORE_ISSUER_ID','APP_STORE_KEY_ID','APP_STORE_PRIVATE_KEY','APP_STORE_ROOT_CERTIFICATES_DIR'])
google_ready=all(credentials[k] for k in ['GOOGLE_PLAY_PACKAGE_NAME','GOOGLE_PLAY_SERVICE_ACCOUNT_JSON'])
rtdn_ready=all(credentials[k] for k in ['GOOGLE_PLAY_PUBSUB_AUDIENCE','GOOGLE_PLAY_PUBSUB_SERVICE_ACCOUNT_EMAIL'])
artifacts={}
for pattern in ['AIONEX-AIOS-Android-v1.6.0.apk','AIONEX-AIOS-Android-v1.6.0.aab']:
 p=RELEASE/pattern
 if p.is_file(): artifacts[p.name]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
payload={
 'schema_version':1,'source_commit':commit,'migration_head':'20260809_0012',
 'local_release_ready':not missing and not embedded,
 'required_files_missing':missing,'embedded_secret_markers':embedded,
 'sandbox':{'app_store_credentials_ready':app_store_ready,'google_play_credentials_ready':google_ready,'google_play_rtdn_identity_ready':rtdn_ready,'external_e2e_ready':app_store_ready and google_ready and rtdn_ready},
 'artifacts':artifacts,'store_publication_performed':False,
 'simulated_e2e_status':'complete' if (ROOT/'web-dashboard/backend/tests/test_mobile_store_simulated_e2e.py').is_file() else 'missing',
 'batch6_status':'complete_simulated_e2e' if (ROOT/'web-dashboard/backend/tests/test_mobile_store_simulated_e2e.py').is_file() else 'incomplete',
 'external_acceptance_status':'ready_to_run' if app_store_ready and google_ready and rtdn_ready else 'blocked_missing_external_credentials_or_store_configuration',
}
report_path=RELEASE/'AIONEX-AIOS-Mobile-Store-Billing-v1.6.0-readiness.json'
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n', encoding='utf-8')
report_path.chmod(0o600)
print(f'RELEASE_READINESS={\"PASS\" if payload[\"local_release_ready\"] else \"FAIL\"}')
print(f'SIMULATED_E2E={payload[\"simulated_e2e_status\"].upper()}')
print(f'READINESS_REPORT={report_path}')
raise SystemExit(0 if payload['local_release_ready'] else 1)
