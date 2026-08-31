from __future__ import annotations

from fastapi import HTTPException
import pytest

from app.services.three_d_policy import DEFAULT_THREE_D_POLICY, normalize_three_d_policy
from app.services.three_d_provider_policy import (
    HUNYUAN_EXCLUDED_COUNTRY_CODES,
    HUNYUAN_LICENSE_SHA256,
    HUNYUAN_LICENSE_SOURCE_COMMIT,
    THREE_D_TERMS_VERSION,
    TRIPOSR_LICENSE_SHA256,
    TRIPOSR_MODEL_REVISION,
    TRIPOSR_SOURCE_COMMIT,
    hunyuan_license_permits_country,
    normalize_country,
    provider_candidates,
    provider_disclosure,
    require_terms_acceptance,
)
from app.services.three_d_resilience import _provider_resource


def _eligible_hunyuan_policy() -> dict:
    return normalize_three_d_policy(
        {
            **DEFAULT_THREE_D_POLICY,
            "hunyuan_license_acknowledged": True,
            "hunyuan_commercial_eligibility_attested": True,
            "service_provider_legal_name_confirmed": True,
            "service_provider_legal_name": "AIONEX AIOS",
        }
    )


def test_hunyuan_license_pin_and_mandatory_territory_are_exact():
    assert HUNYUAN_LICENSE_SOURCE_COMMIT == "82920d643c0dc2f7bfd7255f45f62d386edfe60c"
    assert (
        HUNYUAN_LICENSE_SHA256
        == "b79ac5e11ce063b6c6570dbe9686a45a03ba08bd248aa6aa82fb342a23a81c0c"
    )
    assert {"GB", "KR", "FR", "DE", "ES", "IT", "SE"} <= HUNYUAN_EXCLUDED_COUNTRY_CODES
    assert len(HUNYUAN_EXCLUDED_COUNTRY_CODES) == 29


def test_hunyuan_is_fail_closed_until_all_owner_attestations_are_present():
    policy = normalize_three_d_policy(DEFAULT_THREE_D_POLICY)
    assert not hunyuan_license_permits_country(policy, "AE")
    policy["hunyuan_license_acknowledged"] = True
    assert not hunyuan_license_permits_country(policy, "AE")
    policy["hunyuan_commercial_eligibility_attested"] = True
    assert not hunyuan_license_permits_country(policy, "AE")
    policy["service_provider_legal_name_confirmed"] = True
    assert hunyuan_license_permits_country(policy, "AE")


def test_owner_cannot_remove_mandatory_hunyuan_excluded_countries():
    policy = normalize_three_d_policy(
        {
            **_eligible_hunyuan_policy(),
            "hunyuan_excluded_country_codes": ["US"],
        }
    )
    assert HUNYUAN_EXCLUDED_COUNTRY_CODES <= set(
        policy["hunyuan_excluded_country_codes"]
    )
    assert "US" in policy["hunyuan_excluded_country_codes"]
    assert not hunyuan_license_permits_country(policy, "GB")
    assert not hunyuan_license_permits_country(policy, "KR")
    assert not hunyuan_license_permits_country(policy, "FR")
    assert hunyuan_license_permits_country(policy, "AE")


def test_unknown_country_never_routes_to_hunyuan_and_mit_fallback_is_worldwide():
    policy = _eligible_hunyuan_policy()
    assert provider_candidates(policy, None) == ["triposr"]
    assert provider_candidates(policy, "FR") == ["triposr"]
    assert provider_candidates(policy, "AE") == ["hunyuan3d", "triposr"]
    policy["fallback_enabled"] = False
    with pytest.raises(HTTPException) as blocked:
        provider_candidates(policy, "FR")
    assert blocked.value.status_code == 451


def test_country_normalization_rejects_unknown_edge_markers():
    assert normalize_country(" ae ") == "AE"
    assert normalize_country("XX") is None
    assert normalize_country("T1") is None
    assert normalize_country("") is None


def test_terms_must_be_accepted_at_the_current_version():
    policy = _eligible_hunyuan_policy()
    assert (
        require_terms_acceptance(policy, accepted=True, version=THREE_D_TERMS_VERSION)
        == THREE_D_TERMS_VERSION
    )
    with pytest.raises(HTTPException) as missing:
        require_terms_acceptance(policy, accepted=False, version=THREE_D_TERMS_VERSION)
    assert missing.value.status_code == 428
    with pytest.raises(HTTPException):
        require_terms_acceptance(policy, accepted=True, version="old")


def test_provider_disclosures_are_explicit_and_fallback_is_pinned_mit():
    policy = _eligible_hunyuan_policy()
    primary = provider_disclosure(policy, "hunyuan3d")
    assert primary["territory_limited"] is True
    assert primary["tencent_affiliation"] is False
    assert primary["operator"] == "AIONEX AIOS"
    fallback = provider_disclosure(policy, "triposr")
    assert fallback["license"] == "MIT"
    assert fallback["territory_limited"] is False
    assert TRIPOSR_SOURCE_COMMIT == "107cefdc244c39106fa830359024f6a2f1c78871"
    assert TRIPOSR_MODEL_REVISION == "5b521936b01fbe1890f6f9baed0254ab6351c04a"
    assert (
        TRIPOSR_LICENSE_SHA256
        == "ade0a66629bdd7e01e46b3296b3851cff0fd27989bca53da470ad6e96ed620fb"
    )


def test_primary_circuit_reuses_the_phase34e_runpod_resource():
    assert _provider_resource("runpod") == "runpod"
    assert _provider_resource("hunyuan3d") == "runpod"
    assert _provider_resource("triposr") == "triposr"


def test_runpod_control_plane_parser_selects_the_exact_endpoint(monkeypatch):
    import json

    from app.services import three_d_provider_policy as provider_policy

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(
                {
                    "data": {
                        "myself": {
                            "endpoints": [
                                {
                                    "id": "other-test-endpoint",
                                    "dataCenterIds": ["EU-RO-1"],
                                },
                                {
                                    "id": "primary-test-endpoint",
                                    "dataCenterIds": ["US-TX-3", "US-GA-1"],
                                },
                            ]
                        }
                    }
                }
            ).encode("utf-8")

    seen = {}

    def urlopen(request, *, timeout):
        seen["authorization"] = request.headers.get("Authorization")
        seen["url"] = request.full_url
        seen["user_agent"] = request.headers.get("User-agent")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(provider_policy.urllib.request, "urlopen", urlopen)
    assert provider_policy._fetch_runpod_endpoint_datacenter_ids(
        "test-key", "primary-test-endpoint"
    ) == ("US-TX-3", "US-GA-1")
    assert seen["authorization"] == "Bearer test-key"
    assert seen["url"] == provider_policy._RUNPOD_GRAPHQL_URL
    assert seen["user_agent"] == "Mozilla/5.0 (compatible; AIONEX-AIOS/34F)"
    assert seen["timeout"] == provider_policy._RUNPOD_CONTROL_PLANE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_hunyuan_runtime_verifies_us_datacenters_and_uses_short_cache(
    monkeypatch,
):
    from app.services import three_d_provider_policy as provider_policy

    monkeypatch.setattr(provider_policy, "HUNYUAN_RUNTIME_SECURITY_APPROVED", True)
    provider_policy._runpod_endpoint_region_cache.clear()
    monkeypatch.setattr(
        provider_policy,
        "_provider_env",
        lambda: {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_ENDPOINT_ID": "primary-test-endpoint",
            "RUNPOD_HUNYUAN_LOCATION": "US",
        },
    )
    calls = {"count": 0}

    def fetch(api_key, endpoint_id):
        assert api_key == "test-key"
        assert endpoint_id == "primary-test-endpoint"
        calls["count"] += 1
        return ("US-TX-3", "US-GA-1")

    monkeypatch.setattr(provider_policy, "_fetch_runpod_endpoint_datacenter_ids", fetch)
    assert await provider_policy.provider_runtime_configured(
        "hunyuan3d", expected_endpoint_id="primary-test-endpoint"
    )
    assert await provider_policy.provider_runtime_configured(
        "hunyuan3d", expected_endpoint_id="primary-test-endpoint"
    )
    assert calls["count"] == 1
    assert not await provider_policy.provider_runtime_configured(
        "hunyuan3d", expected_endpoint_id="stale-test-endpoint"
    )
    assert not await provider_policy.provider_runtime_configured(
        "hunyuan3d", expected_endpoint_id=""
    )
    assert calls["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "datacenter_ids",
    [
        None,
        (),
        ("US-TX-3", "EU-RO-1"),
    ],
)
async def test_hunyuan_runtime_fails_closed_for_missing_empty_or_non_us_regions(
    monkeypatch, datacenter_ids
):
    from app.services import three_d_provider_policy as provider_policy

    monkeypatch.setattr(provider_policy, "HUNYUAN_RUNTIME_SECURITY_APPROVED", True)
    provider_policy._runpod_endpoint_region_cache.clear()
    monkeypatch.setattr(
        provider_policy,
        "_provider_env",
        lambda: {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_ENDPOINT_ID": "primary-test-endpoint",
            "RUNPOD_HUNYUAN_LOCATION": "US",
        },
    )
    monkeypatch.setattr(
        provider_policy,
        "_fetch_runpod_endpoint_datacenter_ids",
        lambda _api_key, _endpoint_id: datacenter_ids,
    )
    assert not await provider_policy.provider_runtime_configured("hunyuan3d")


@pytest.mark.asyncio
async def test_hunyuan_control_plane_error_blocks_primary_but_not_triposr(
    monkeypatch,
):
    from app.services import three_d_provider_policy as provider_policy

    monkeypatch.setattr(provider_policy, "HUNYUAN_RUNTIME_SECURITY_APPROVED", True)
    provider_policy._runpod_endpoint_region_cache.clear()
    monkeypatch.setattr(
        provider_policy,
        "_provider_env",
        lambda: {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_ENDPOINT_ID": "primary-test-endpoint",
            "RUNPOD_FALLBACK_ENDPOINT_ID": "fallback-test-endpoint",
            "RUNPOD_HUNYUAN_LOCATION": "US",
        },
    )

    def fail(_api_key, _endpoint_id):
        raise OSError("control plane unavailable")

    monkeypatch.setattr(provider_policy, "_fetch_runpod_endpoint_datacenter_ids", fail)
    assert not await provider_policy.provider_runtime_configured("hunyuan3d")
    assert await provider_policy.provider_runtime_configured("triposr")


@pytest.mark.asyncio
async def test_hunyuan_runtime_is_technically_quarantined_by_default(monkeypatch):
    from app.services import three_d_provider_policy as provider_policy

    assert provider_policy.HUNYUAN_RUNTIME_SECURITY_APPROVED is False
    assert provider_policy.HUNYUAN_QUARANTINED_IMAGE_DIGEST.startswith("sha256:")
    monkeypatch.setattr(
        provider_policy,
        "_provider_env",
        lambda: {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_ENDPOINT_ID": "primary-test-endpoint",
            "RUNPOD_HUNYUAN_LOCATION": "US",
        },
    )
    assert not await provider_policy.provider_runtime_configured("hunyuan3d")

def test_worker_clients_allow_fallback_without_primary_endpoint(monkeypatch):
    from app.services import three_d_worker

    monkeypatch.setattr(
        three_d_worker,
        "_env_file",
        lambda _path: {
            "RUNPOD_API_KEY": "test-key",
            "RUNPOD_FALLBACK_ENDPOINT_ID": "triposr-endpoint",
        },
    )
    clients = three_d_worker._runpod_clients()
    assert set(clients) == {"triposr"}


@pytest.mark.asyncio
async def test_worker_preflight_isolates_a_failed_primary_when_fallback_is_healthy(
    monkeypatch,
):
    from app.services import three_d_worker

    class Storage:
        def preflight(self):
            return None

    class Client:
        def __init__(self, *, fail: bool):
            self.fail = fail

        def health(self):
            if self.fail:
                raise RuntimeError("provider unavailable")
            return {"workers": {}}

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return None

    async def policy(_session):
        return {"fallback_enabled": True}

    monkeypatch.setattr(three_d_worker, "SessionLocal", Session)
    monkeypatch.setattr(three_d_worker, "get_three_d_policy", policy)
    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.storage = Storage()
    worker.runpods = {
        "hunyuan3d": Client(fail=True),
        "triposr": Client(fail=False),
    }
    await worker.preflight()


def test_worker_submission_and_clarification_recheck_fail_closed_gates():
    from inspect import getsource

    from app.api.v1.endpoints.three_d_jobs import clarify_three_d_job
    from app.services.three_d_worker import ThreeDGenerationWorker

    execute_source = getsource(ThreeDGenerationWorker.execute)
    assert "assert_provider_available(" in execute_source
    assert "_defer_for_open_circuit(" in execute_source
    clarify_source = getsource(clarify_three_d_job)
    assert "_licensed_provider_route(" in clarify_source
    assert "require_terms_acceptance(" in clarify_source
    assert "job.provider = provider" in clarify_source
    assert '"third_party_terms_version": accepted_terms_version' in clarify_source
