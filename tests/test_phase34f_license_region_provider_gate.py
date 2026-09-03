from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
POLICY = (BACKEND / "app/services/three_d_provider_policy.py").read_text()
SERVICE_POLICY = (BACKEND / "app/services/three_d_policy.py").read_text()
API = (BACKEND / "app/api/v1/endpoints/three_d_jobs.py").read_text()
WORKER = (BACKEND / "app/services/three_d_worker.py").read_text()
OWNER = (BACKEND / "app/api/owner/three_d.py").read_text()
TRIPOSR_DOCKER = (ROOT / "infra/runpod/triposr/Dockerfile").read_text()
TRIPOSR_HANDLER = (ROOT / "infra/runpod/triposr/handler.py").read_text()
TERMS_UI = (ROOT / "vip-frontend/src/components/pages/three-d-project-panel.tsx").read_text()
LEGAL_UI = (ROOT / "vip-frontend/src/components/pages/legal-client.tsx").read_text()


def test_exact_license_copies_and_pins_are_tracked():
    hunyuan = ROOT / "vip-frontend/public/legal/tencent-hunyuan-3d-2.1-license.txt"
    triposr = ROOT / "vip-frontend/public/legal/triposr-mit-license.txt"
    assert sha256(hunyuan.read_bytes()).hexdigest() == "b79ac5e11ce063b6c6570dbe9686a45a03ba08bd248aa6aa82fb342a23a81c0c"
    assert sha256(triposr.read_bytes()).hexdigest() == "ade0a66629bdd7e01e46b3296b3851cff0fd27989bca53da470ad6e96ed620fb"
    assert "82920d643c0dc2f7bfd7255f45f62d386edfe60c" in POLICY
    assert "107cefdc244c39106fa830359024f6a2f1c78871" in POLICY + TRIPOSR_HANDLER
    assert "5b521936b01fbe1890f6f9baed0254ab6351c04a" in POLICY + TRIPOSR_DOCKER + TRIPOSR_HANDLER


def test_hunyuan_is_fail_closed_and_excluded_regions_are_mandatory():
    assert '"hunyuan_license_acknowledged": False' in SERVICE_POLICY
    assert '"hunyuan_commercial_eligibility_attested": False' in SERVICE_POLICY
    assert '"service_provider_legal_name_confirmed": False' in SERVICE_POLICY
    for code in ("GB", "KR", "FR", "DE", "IT", "ES"):
        assert f'"{code}"' in SERVICE_POLICY
    assert "HUNYUAN_EXCLUDED_COUNTRY_CODES" in POLICY
    assert "country is None" in POLICY


def test_routing_requires_current_terms_and_never_serves_hunyuan_output_outside_territory():
    assert "provider_candidates(policy, country)" in API
    assert "await provider_runtime_configured(provider)" in API
    assert "RUNPOD_HUNYUAN_LOCATION" in POLICY
    assert "dataCenterIds" in POLICY
    assert '"Authorization": f"Bearer {api_key}"' in POLICY
    assert "urllib.parse" not in POLICY
    assert '"User-Agent": "Mozilla/5.0 (compatible; AIONEX-AIOS/34F)"' in POLICY
    assert "require_terms_acceptance(" in API
    assert "THREE_D_HUNYUAN_OUTPUT_TERRITORY_BLOCKED" in API
    assert 'status_code=451' in API
    assert 'third_party_terms_accepted: Annotated[bool, Form()]' in API
    clarify = API.split("async def clarify_three_d_job", 1)[1].split(
        '@router.get("/{project_id}/3d/jobs/{job_id}/artifact")', 1
    )[0]
    assert "_licensed_provider_route(" in clarify
    assert "require_terms_acceptance(" in clarify
    assert "job.provider = provider" in clarify


def test_worldwide_fallback_is_real_pinned_triposr_not_placeholder():
    assert "pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime@sha256:" in TRIPOSR_DOCKER
    assert "torchmcubes" not in TRIPOSR_DOCKER
    assert "snapshot_download" in TRIPOSR_DOCKER
    assert "scikit-image==0.26.0" in (ROOT / "infra/runpod/triposr/requirements.txt").read_text()
    requirements = (ROOT / "infra/runpod/triposr/requirements.txt").read_text()
    assert "numpy==2.3.5" in requirements
    assert "transformers==5.10.1" in requirements
    assert "runpod==1.11.0" in requirements
    assert "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2" in TRIPOSR_DOCKER
    assert "/models/dino-vitb16" in TRIPOSR_DOCKER
    assert '"pipeline": "triposr-mit-textured-fallback"' in TRIPOSR_HANDLER
    assert '"fallback_provider": "triposr"' in TRIPOSR_HANDLER
    assert '"license": "MIT"' in TRIPOSR_HANDLER
    assert "trimesh.exchange.gltf.export_glb" in TRIPOSR_HANDLER
    assert "round-trip validation" in TRIPOSR_HANDLER
    bake = (ROOT / "infra/runpod/triposr/vendor/tsr/bake_texture.py").read_text()
    assert "device=scene_code.device" in bake
    assert ".detach().cpu().numpy()" in bake
    assert 'self.runpods.get(key)' in WORKER
    assert 'RUNPOD_FALLBACK_ENDPOINT_ID' in WORKER


def test_owner_controls_license_fallback_and_territory_policy():
    for token in (
        "hunyuan_license_acknowledged",
        "hunyuan_commercial_eligibility_attested",
        "service_provider_legal_name_confirmed",
        "hunyuan_excluded_country_codes",
        "fallback_enabled",
        "service_provider_legal_name",
        "third_party_terms_version",
    ):
        assert token in OWNER and token in SERVICE_POLICY


def test_user_ui_discloses_provider_and_requires_terms_acceptance():
    assert "model_disclosure.model" in TERMS_UI
    assert "hunyuanNoAffiliation" in TERMS_UI
    assert "termsAccepted" in TERMS_UI
    assert "clarifyProjectThreeDJob(" in TERMS_UI
    assert "third_party_terms_version" in TERMS_UI
    assert "/legal/terms" in TERMS_UI
    assert "terms5" in LEGAL_UI or "[1, 2, 3, 4, 5, 6]" in LEGAL_UI
    assert "tencent-hunyuan-3d-2.1-license.txt" in LEGAL_UI
    assert "triposr-mit-license.txt" in LEGAL_UI
