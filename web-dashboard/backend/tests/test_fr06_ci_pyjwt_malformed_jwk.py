"""CVE-2026-102274 regression and JWT rejection controls; synthetic keys only.

No external JWKS fetch, production secret, billing mutation or provider I/O.
Malformed RSA JWKs must not disable valid sibling signing keys, while token
signature, algorithm, issuer, audience and expiration checks remain enforced.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _keys(key: rsa.RSAPrivateKey) -> tuple[dict[str, Any], dict[str, Any]]:
    good = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    good.update(kid="owned-valid-key", use="sig", alg="RS256")
    bad = {**good, "kid": "synthetic-invalid-key", "d": "AAAAAA"}
    return good, bad


def _claims() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "sub": "synthetic-user",
        "iss": "https://issuer.example.invalid",
        "aud": "isolated-aionex",
        "iat": now,
        "exp": now + timedelta(minutes=2),
    }


def _decode(token: str, key: Any, algorithm: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        issuer="https://issuer.example.invalid",
        audience="isolated-aionex",
        options={"require": ["exp", "sub", "iss", "aud"]},
    )


@pytest.mark.parametrize("bad_first", [False, True])
def test_bad_rsa_key_is_skipped_but_good_signature_key_remains(
    rsa_key: rsa.RSAPrivateKey, bad_first: bool
) -> None:
    good, bad = _keys(rsa_key)
    keys = jwt.PyJWKSet.from_dict({"keys": [bad, good] if bad_first else [good, bad]})
    assert len(keys.keys) == 1 and keys.keys[0].key_id == good["kid"]
    token = jwt.encode(_claims(), rsa_key, algorithm="RS256", headers={"kid": good["kid"]})
    assert _decode(token, keys.keys[0].key, "RS256")["sub"] == "synthetic-user"


def test_direct_malformed_rsa_key_raises_documented_exception(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    _, bad = _keys(rsa_key)
    with pytest.raises(jwt.InvalidKeyError) as caught:
        jwt.PyJWK.from_dict(bad)
    assert isinstance(caught.value.__cause__, ValueError)


def test_all_malformed_keys_fail_instead_of_accepting_an_empty_trust_set(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    _, bad = _keys(rsa_key)
    with pytest.raises(jwt.PyJWKSetError):
        jwt.PyJWKSet.from_dict({"keys": [bad]})


@pytest.mark.parametrize("bad_first", [False, True])
def test_public_jwks_client_flow_preserves_valid_sibling_without_network(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch, bad_first: bool
) -> None:
    good, bad = _keys(rsa_key)
    client = jwt.PyJWKClient("https://jwks.example.invalid/keys")
    calls: list[bool] = []

    def fetched() -> dict[str, Any]:
        calls.append(True)
        return {"keys": [bad, good] if bad_first else [good, bad]}

    monkeypatch.setattr(client, "fetch_data", fetched)
    token = jwt.encode(_claims(), rsa_key, algorithm="RS256", headers={"kid": good["kid"]})
    signing_key = client.get_signing_key_from_jwt(token)
    assert signing_key.key_id == good["kid"] and calls
    assert _decode(token, signing_key.key, "RS256")["sub"] == "synthetic-user"


def test_unknown_signing_key_id_is_not_substituted(
    rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = _keys(rsa_key)
    client = jwt.PyJWKClient("https://jwks.example.invalid/keys")
    monkeypatch.setattr(client, "fetch_data", lambda: {"keys": [bad, good]})
    token = jwt.encode(_claims(), rsa_key, algorithm="RS256", headers={"kid": "not-in-trust-set"})
    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key_from_jwt(token)


@pytest.mark.parametrize("algorithm", ["HS256", "RS256"])
@pytest.mark.parametrize("problem", ["expired", "issuer", "audience", "missing-exp", "signature", "unsigned"])
def test_fixed_jwks_parser_does_not_weaken_token_verification(
    rsa_key: rsa.RSAPrivateKey, algorithm: str, problem: str
) -> None:
    signing: Any = rsa_key if algorithm == "RS256" else "synthetic-hmac-value-at-least-32-characters"
    verification: Any = rsa_key.public_key() if algorithm == "RS256" else signing
    claims = _claims()
    if problem == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif problem == "issuer":
        claims["iss"] = "https://wrong-issuer.example.invalid"
    elif problem == "audience":
        claims["aud"] = "wrong-recipient"
    elif problem == "missing-exp":
        del claims["exp"]
    if problem == "unsigned":
        token = jwt.encode(claims, "", algorithm="none")
    else:
        token = jwt.encode(claims, signing, algorithm=algorithm)
    if problem == "signature":
        verification = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
            if algorithm == "RS256" else "different-synthetic-hmac-value-at-least-32-characters"
        )
    with pytest.raises(jwt.InvalidTokenError):
        _decode(token, verification, algorithm)


@pytest.mark.parametrize("algorithm", ["HS256", "RS256"])
def test_accepted_token_claims_and_signature_are_unchanged(
    rsa_key: rsa.RSAPrivateKey, algorithm: str
) -> None:
    signing: Any = rsa_key if algorithm == "RS256" else "synthetic-hmac-value-at-least-32-characters"
    verification = rsa_key.public_key() if algorithm == "RS256" else signing
    token = jwt.encode(_claims(), signing, algorithm=algorithm)
    decoded = _decode(token, verification, algorithm)
    assert decoded["sub"] == "synthetic-user" and decoded["aud"] == "isolated-aionex"
