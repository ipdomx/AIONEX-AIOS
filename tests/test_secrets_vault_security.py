from hashlib import sha256
from secrets import token_bytes

import pytest

from aios.infrastructure.secrets import InMemorySecretBackend, SecretsVault


def _legacy_blob(master_key: bytes, value: str) -> bytes:
    key = sha256(master_key).digest()
    raw = value.encode("utf-8")
    nonce = token_bytes(16)
    output = bytearray()
    counter = 0
    while len(output) < len(raw):
        output.extend(sha256(key + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    stream = bytes(output[: len(raw)])
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    tag = sha256(key + nonce + cipher).digest()
    return nonce + tag + cipher


def test_new_vault_records_use_versioned_aes_gcm_and_round_trip() -> None:
    backend = InMemorySecretBackend()
    vault = SecretsVault(b"a-long-enough-master-key-for-tests", backend)
    vault.put("provider/token", "top-secret-value")
    blob = backend.get("provider/token")
    assert blob.startswith(SecretsVault._V2_PREFIX)
    assert b"top-secret-value" not in blob
    assert vault.get("provider/token") == "top-secret-value"


def test_aes_gcm_tamper_is_rejected() -> None:
    backend = InMemorySecretBackend()
    vault = SecretsVault(b"a-long-enough-master-key-for-tests", backend)
    vault.put("provider/token", "top-secret-value")
    blob = bytearray(backend.get("provider/token"))
    blob[-1] ^= 1
    backend.put("provider/token", bytes(blob))
    with pytest.raises(ValueError, match="integrity"):
        vault.get("provider/token")


def test_legacy_record_is_read_once_and_transparently_resealed_as_v2() -> None:
    master_key = b"a-long-enough-master-key-for-tests"
    backend = InMemorySecretBackend()
    backend.put("legacy", _legacy_blob(master_key, "legacy-secret"))
    assert not backend.get("legacy").startswith(SecretsVault._V2_PREFIX)
    vault = SecretsVault(master_key, backend)
    assert vault.get("legacy") == "legacy-secret"
    assert backend.get("legacy").startswith(SecretsVault._V2_PREFIX)
    assert vault.get("legacy") == "legacy-secret"


def test_wrong_master_key_cannot_open_versioned_record() -> None:
    backend = InMemorySecretBackend()
    first = SecretsVault(b"correct-master-key-material", backend)
    first.put("secret", "value")
    second = SecretsVault(b"different-master-key-material", backend)
    with pytest.raises(ValueError, match="integrity"):
        second.get("secret")
