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
