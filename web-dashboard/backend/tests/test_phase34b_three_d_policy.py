from app.services.three_d_policy import DEFAULT_THREE_D_POLICY, normalize_three_d_policy, three_d_access_allowed

def test_3d_defaults_to_highest_current_plan_only():
    p=normalize_three_d_policy({})
    assert p["allowed_plan_codes"] == ["business"]
    assert p["required_entitlement"] == "3d.generation"

def test_3d_access_requires_owner_policy_plan_and_entitlement():
    p=normalize_three_d_policy(DEFAULT_THREE_D_POLICY)
    assert three_d_access_allowed(p,user_id="u1",plan_code="business",entitlements=["3d.generation"])
    assert not three_d_access_allowed(p,user_id="u1",plan_code="professional",entitlements=["3d.generation"])
    assert not three_d_access_allowed(p,user_id="u1",plan_code="business",entitlements=[])

def test_owner_can_override_or_deny_individual_users():
    p=normalize_three_d_policy({**DEFAULT_THREE_D_POLICY,"allowed_user_ids":["u-pro"],"denied_user_ids":["u-block"]})
    assert three_d_access_allowed(p,user_id="u-pro",plan_code="professional",entitlements=[])
    assert not three_d_access_allowed(p,user_id="u-block",plan_code="business",entitlements=["3d.generation"])


def test_business_portal_plan_carries_3d_entitlement():
    from app.services.portal_cms import default_portal_configuration
    config = default_portal_configuration()
    business = next(plan for plan in config["pricing"]["plans"] if plan["id"] == "business")
    professional = next(plan for plan in config["pricing"]["plans"] if plan["id"] == "professional")
    assert "3d.generation" in business["entitlements"]
    assert "3d.generation" not in professional["entitlements"]
