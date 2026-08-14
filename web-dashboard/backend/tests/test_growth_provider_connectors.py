from app.services import growth_provider_connectors as connectors


def test_catalog_is_fail_closed_for_live_mutation():
    catalog = connectors.connector_catalog()
    assert catalog
    assert all(item["live_mutation_allowed"] is False for item in catalog)
    assert all("contract" in item["supported_validation_modes"] for item in catalog)


def test_raw_credentials_and_live_modes_are_rejected():
    assert connectors.validate_credential_ref("token=abc")[0] is False
    assert connectors.validate_credential_ref("Bearer secret")[0] is False
    live = connectors.validation_preview(
        "meta", "ads.read", "live_spend", "secretref://meta/account", True
    )
    assert live["allowed"] is False
    assert live["provider_call_allowed"] is False
    assert live["mutation_allowed"] is False
    assert live["spend_allowed"] is False


def test_contract_validation_never_calls_provider_or_verifies_live():
    result = connectors.validation_preview("meta", "ads.read", "contract", None, False)
    assert result == {
        "allowed": True,
        "reason": "contract-validation-only",
        "verification_state": "unverified",
        "provider_call_allowed": False,
        "mutation_allowed": False,
        "spend_allowed": False,
    }


def test_read_only_and_sandbox_require_reference_and_platform_approval():
    missing = connectors.validation_preview("meta", "ads.read", "read_only", None, True)
    assert missing["allowed"] is False
    assert missing["reason"] == "credential-reference-missing"

    not_approved = connectors.validation_preview(
        "meta", "ads.read", "read_only", "secretref://meta/account", False
    )
    assert not_approved["allowed"] is False
    assert not_approved["reason"] == "platform-approval-required"

    ready = connectors.validation_preview(
        "meta", "ads.read", "read_only", "secretref://meta/account", True
    )
    assert ready["allowed"] is True
    assert ready["verification_state"] == "read_only_ready"
    assert ready["provider_call_allowed"] is True
    assert ready["mutation_allowed"] is False
    assert ready["spend_allowed"] is False

    sandbox = connectors.validation_preview(
        "tiktok", "ads.read", "sandbox", "secretref://tiktok/account", True
    )
    assert sandbox["allowed"] is True
    assert sandbox["verification_state"] == "sandbox_ready"
    assert sandbox["mutation_allowed"] is False
    assert sandbox["spend_allowed"] is False
