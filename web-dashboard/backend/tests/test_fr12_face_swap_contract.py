from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from app.services.face_swap_adapter import FaceSwapReplicateAdapter, single_output_url
from app.services.face_swap_contract import (
    FACE_SWAP_AMBIGUOUS_SUBMISSION_REPLAY,
    FACE_SWAP_MAX_ATTEMPTS,
    FACE_SWAP_MODEL_VERSION,
    FACE_SWAP_RUNTIME_APPROVED,
    FaceSwapAuthorization,
    FaceSwapContractError,
    FaceSwapExecutionContract,
    FaceSwapStoredInput,
    validate_output_image,
)
from app.services.identity_media_replicate import IdentityMediaProviderFailure


SHA_A = "a" * 64
SHA_B = "b" * 64
TARGET_URL = (
    "https://api.vip-e.net/api/v1/studio/identity-media/provider-input/"
    "signed-target/target.png"
)
SOURCE_URL = (
    "https://api.vip-e.net/api/v1/studio/identity-media/provider-input/"
    "signed-source/source.png"
)


def _input(name: str, checksum: str) -> FaceSwapStoredInput:
    return FaceSwapStoredInput(
        input_name=name,  # type: ignore[arg-type]
        storage_key=f"identity-media/exec-1/{name}.png",
        checksum_sha256=checksum,
        content_type="image/png",
        filename=f"{name}.png",
    )


def _authorization() -> FaceSwapAuthorization:
    return FaceSwapAuthorization(
        identity_basis="consented_person",
        subject_reference="consented-subject-1",
        rights_evidence_sha256=SHA_B,
        owner_approval_version=4,
        synthetic_media_disclosure_accepted=True,
    )


def test_contract_is_fail_closed_until_runtime_integration() -> None:
    contract = FaceSwapExecutionContract(
        execution_id="exec-1",
        organization_id="org-1",
        project_id="project-1",
        idempotency_key="faceswap:exec-1",
        target_image=_input("target_image", SHA_A),
        source_face=_input("source_face", SHA_B),
        authorization=_authorization(),
        approved_max_cost_usd="2.5",
    )

    assert FACE_SWAP_RUNTIME_APPROVED is False
    assert contract.provider_runtime_approved is False
    assert FACE_SWAP_MAX_ATTEMPTS == 1
    assert contract.max_attempts == 1
    assert FACE_SWAP_AMBIGUOUS_SUBMISSION_REPLAY is False
    assert contract.ambiguous_submission_replay is False
    assert contract.approved_max_cost_usd == Decimal("2.500000")


def test_real_person_requires_rights_owner_approval_and_disclosure() -> None:
    with pytest.raises(FaceSwapContractError, match="owner-approval-required"):
        FaceSwapAuthorization(
            identity_basis="self",
            subject_reference="owner",
            rights_evidence_sha256=SHA_A,
            owner_approval_version=None,
            synthetic_media_disclosure_accepted=True,
        )
    with pytest.raises(FaceSwapContractError, match="rights-evidence-required"):
        FaceSwapAuthorization(
            identity_basis="consented_person",
            subject_reference="subject",
            rights_evidence_sha256=None,
            owner_approval_version=1,
            synthetic_media_disclosure_accepted=True,
        )
    with pytest.raises(FaceSwapContractError, match="synthetic-media-disclosure-required"):
        FaceSwapAuthorization(
            identity_basis="licensed_public_figure",
            subject_reference="licensed-subject",
            rights_evidence_sha256=SHA_A,
            owner_approval_version=1,
            synthetic_media_disclosure_accepted=False,
        )


def test_private_input_contract_rejects_path_escape_and_wrong_media() -> None:
    with pytest.raises(FaceSwapContractError, match="storage-key-invalid"):
        FaceSwapStoredInput(
            input_name="target_image",
            storage_key="../outside.png",
            checksum_sha256=SHA_A,
            content_type="image/png",
            filename="target.png",
        )
    with pytest.raises(FaceSwapContractError, match="content-type-rejected"):
        FaceSwapStoredInput(
            input_name="source_face",
            storage_key="identity-media/source.gif",
            checksum_sha256=SHA_A,
            content_type="image/gif",
            filename="source.gif",
        )


def test_output_image_requires_matching_binary_envelope() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"safe-fixture"
    evidence = validate_output_image(png, "image/png; charset=binary")
    assert evidence.media_type == "image/png"
    assert evidence.suffix == ".png"
    assert evidence.size_bytes == len(png)
    assert len(evidence.checksum_sha256) == 64

    with pytest.raises(FaceSwapContractError, match="output-content-type-mismatch"):
        validate_output_image(png, "image/jpeg")
    with pytest.raises(FaceSwapContractError, match="output-image-envelope-rejected"):
        validate_output_image(b"not-an-image", "image/png")


def test_adapter_submits_pinned_version_once_with_signed_inputs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == "https://api.replicate.com/v1/predictions"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["cancel-after"] == "600s"
        payload = json.loads(request.content)
        assert payload == {
            "version": FACE_SWAP_MODEL_VERSION,
            "input": {
                "input_image": TARGET_URL,
                "swap_image": SOURCE_URL,
            },
        }
        return httpx.Response(
            201,
            json={
                "id": "prediction-1",
                "status": "starting",
                "output": None,
                "metrics": {},
            },
        )

    adapter = FaceSwapReplicateAdapter(
        "test-token",
        transport=httpx.MockTransport(handler),
    )
    prediction = asyncio.run(
        adapter.submit(
            target_image_url=TARGET_URL,
            source_face_url=SOURCE_URL,
        )
    )

    assert prediction.prediction_id == "prediction-1"
    assert prediction.status == "starting"
    assert len(requests) == 1


@pytest.mark.parametrize("failure_mode", ["timeout", "server"])
def test_adapter_never_replays_ambiguous_submission(failure_mode: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure_mode == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(503, json={"detail": "unavailable"})

    adapter = FaceSwapReplicateAdapter(
        "test-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(
        IdentityMediaProviderFailure,
        match="provider_submission_ambiguous",
    ) as caught:
        asyncio.run(
            adapter.submit(
                target_image_url=TARGET_URL,
                source_face_url=SOURCE_URL,
            )
        )

    assert caught.value.ambiguous_submission is True
    assert calls == 1


def test_adapter_polls_and_downloads_only_trusted_single_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.replicate.com/v1/predictions/prediction-1":
            return httpx.Response(
                200,
                json={
                    "id": "prediction-1",
                    "status": "succeeded",
                    "output": "https://replicate.delivery/pbxt/result.png",
                    "metrics": {"predict_time": 1.5},
                },
            )
        if str(request.url) == "https://replicate.delivery/pbxt/result.png":
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nfixture",
                headers={"content-type": "image/png"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = FaceSwapReplicateAdapter(
        "test-token",
        transport=httpx.MockTransport(handler),
    )
    prediction = asyncio.run(adapter.get_prediction("prediction-1"))
    assert prediction.status == "succeeded"
    assert prediction.metrics["predict_time"] == 1.5

    body, media = asyncio.run(adapter.download_output(prediction.output))
    assert body.startswith(b"\x89PNG")
    assert media == "image/png"

    with pytest.raises(IdentityMediaProviderFailure, match="provider_output_invalid"):
        single_output_url(
            [
                "https://replicate.delivery/pbxt/a.png",
                "https://replicate.delivery/pbxt/b.png",
            ]
        )
    with pytest.raises(IdentityMediaProviderFailure, match="provider_output_host_rejected"):
        single_output_url("https://example.com/output.png")


def test_adapter_rejects_untrusted_provider_and_unsigned_input_shape() -> None:
    with pytest.raises(IdentityMediaProviderFailure, match="provider_base_url_rejected"):
        FaceSwapReplicateAdapter("test-token", base_url="https://example.com")

    adapter = FaceSwapReplicateAdapter(
        "test-token",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        ),
    )
    with pytest.raises(IdentityMediaProviderFailure, match="provider_input_url_invalid"):
        asyncio.run(
            adapter.submit(
                target_image_url=(
                    "http://api.vip-e.net/api/v1/studio/identity-media/"
                    "provider-input/x/a.png"
                ),
                source_face_url=SOURCE_URL,
            )
        )
