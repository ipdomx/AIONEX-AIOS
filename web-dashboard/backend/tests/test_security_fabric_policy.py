import pytest
from app.services.security_fabric import host_matches_suffix, normalize_origin, profile_allowed


def test_origin_normalization_and_path_rejection():
    assert normalize_origin("https://Example.COM/") == ("https://example.com", "example.com")
    with pytest.raises(ValueError):
        normalize_origin("https://example.com/admin")
    with pytest.raises(ValueError):
        normalize_origin("https://user:pass@example.com")


def test_managed_domain_matching_does_not_accept_suffix_confusion():
    assert host_matches_suffix("app.vip-e.net", ["vip-e.net"])
    assert host_matches_suffix("vip-e.net", ["vip-e.net"])
    assert not host_matches_suffix("evilvip-e.net", ["vip-e.net"])


def test_entitlement_profile_ceiling():
    assert profile_allowed("standard", "standard")
    assert not profile_allowed("standard", "advanced")
    assert profile_allowed("elite", "elite")
    assert profile_allowed("owner", "elite")
    assert not profile_allowed(None, "passive")
