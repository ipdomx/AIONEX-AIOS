from __future__ import annotations

import json
from importlib.metadata import version

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)


def test_webauthn3_registration_and_authentication_options_match_aionex_policy() -> None:
    assert version("webauthn") == "3.0.0"

    registration = generate_registration_options(
        rp_id="ai.vip-e.net",
        rp_name="AIONEX",
        user_id=b"user-1",
        user_name="user@example.com",
        user_display_name="User One",
        challenge=b"r" * 32,
        timeout=120_000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    registration_json = json.loads(options_to_json(registration))
    assert registration_json["rp"]["id"] == "ai.vip-e.net"
    assert registration_json["authenticatorSelection"] == {
        "authenticatorAttachment": "platform",
        "residentKey": "required",
        "requireResidentKey": True,
        "userVerification": "required",
    }
    assert registration_json["timeout"] == 120_000

    authentication = generate_authentication_options(
        rp_id="ai.vip-e.net",
        challenge=b"a" * 32,
        timeout=120_000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    authentication_json = json.loads(options_to_json(authentication))
    assert authentication_json["rpId"] == "ai.vip-e.net"
    assert authentication_json["userVerification"] == "required"
    assert authentication_json["timeout"] == 120_000
