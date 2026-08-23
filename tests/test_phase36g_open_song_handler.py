from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import wave

import pytest
from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_LANGUAGE_MODEL_REVISION,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_SOURCE_COMMIT,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_SOURCE_COMMIT,
)

ROOT = Path(__file__).resolve().parents[1]
HANDLER_ROOT = ROOT / "infra/runpod/open_song"
SPEC = importlib.util.spec_from_file_location(
    "aionex_open_song_handler_contract", HANDLER_ROOT / "contract.py"
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)

HANDLER_IMAGE_DIGEST = "sha256:" + "8" * 64


def payload() -> dict:
    return {
        "schema": "aionex.open-song-request.v1",
        "route_id": "runpod-flex-a40",
        "model": "acestep-v15-base",
        "model_revision": ACE_STEP_MODEL_REVISION,
        "language_model": "acestep-5Hz-lm-4B",
        "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
        "source_commit": ACE_STEP_SOURCE_COMMIT,
        "container_image_digest": HANDLER_IMAGE_DIGEST,
        "separation": {
            "model": "htdemucs",
            "source_commit": DEMUCS_SOURCE_COMMIT,
            "checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
            "stems": ["vocals", "drums", "bass", "other"],
        },
        "song": {
            "title": "Original governed handler song",
            "concept": (
                "Original cinematic electronic pop with warm drums, synthetic vocals, "
                "a strong chorus, and a clean resolved ending."
            ),
            "lyrics": (
                "[Verse]\nA new horizon rises from the night.\n"
                "[Chorus]\nWe build the future in the morning light."
            ),
            "language": "en",
            "duration_seconds": 30,
            "bpm": 104,
            "musical_key": "Am",
            "time_signature": 4,
            "seed": 36_008,
        },
        "output": {
            "media_type": "audio/wav",
            "sample_rate_hz": 48_000,
            "channels": 2,
            "stems": ["vocals", "drums", "bass", "other"],
        },
        "safety": {
            "max_attempts": 1,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
            "known_person_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
            "ai_generated_disclosure_required": True,
        },
    }


def wav_file(tmp_path: Path, name: str = "audio.wav") -> Path:
    path = tmp_path / name
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(b"\x00\x00\x00\x00" * 48_000)
    return path


def test_handler_supply_chain_matches_governed_factory() -> None:
    assert contract.ACE_STEP_SOURCE_COMMIT == ACE_STEP_SOURCE_COMMIT
    assert contract.ACE_STEP_MODEL_REVISION == ACE_STEP_MODEL_REVISION
    assert contract.ACE_STEP_LANGUAGE_MODEL_REVISION == ACE_STEP_LANGUAGE_MODEL_REVISION
    assert contract.DEMUCS_SOURCE_COMMIT == DEMUCS_SOURCE_COMMIT
    assert contract.DEMUCS_CHECKPOINT_SHA256 == DEMUCS_CHECKPOINT_SHA256


def test_request_is_exact_one_attempt_and_private_input_stays_internal() -> None:
    request = contract.HandlerSongRequest.from_payload(
        payload(), expected_image_digest=HANDLER_IMAGE_DIGEST
    )
    ace = request.ace_step_api_payload()
    assert ace["model"] == "acestep-v15-base"
    assert ace["lm_model_path"] == "acestep-5Hz-lm-4B"
    assert ace["batch_size"] == 1
    assert ace["use_random_seed"] is False
    assert ace["seed"] == "36008"
    assert ace["audio_format"] == "wav"
    assert request.lyrics not in repr(payload()["safety"])


@pytest.mark.parametrize(
    "mutator,match",
    (
        (lambda value: value["safety"].__setitem__("automatic_retry", True), "safety"),
        (lambda value: value.__setitem__("container_image_digest", "sha256:" + "7" * 64), "image"),
        (lambda value: value["separation"].__setitem__("stems", ["vocals"]), "stem"),
        (
            lambda value: value["song"].__setitem__(
                "concept", "Create this in the style of a famous singer with copied identity."
            ),
            "imitation",
        ),
    ),
)
def test_request_rejects_relaxed_or_drifted_contract(mutator, match: str) -> None:
    value = payload()
    mutator(value)
    with pytest.raises(contract.OpenSongHandlerContractError, match=match):
        contract.HandlerSongRequest.from_payload(
            value, expected_image_digest=HANDLER_IMAGE_DIGEST
        )


def test_wav_evidence_and_local_commands_are_bounded(tmp_path: Path) -> None:
    source = wav_file(tmp_path)
    evidence = contract.inspect_wav(source)
    assert evidence.sample_rate_hz == 48_000
    assert evidence.channels == 2
    assert evidence.duration_seconds == 1.0
    demucs = contract.demucs_command(source, tmp_path / "stems")
    assert demucs[:4] == ["python", "-m", "demucs.separate", "--device"]
    assert "955717e8" in demucs
    assert "--shifts" in demucs and demucs[demucs.index("--shifts") + 1] == "1"
    canonical = contract.canonicalize_command(source, tmp_path / "canonical.wav")
    assert canonical[0] == "ffmpeg"
    assert canonical[canonical.index("-ar") + 1] == "48000"
    assert canonical[canonical.index("-ac") + 1] == "2"


def test_ace_step_response_parsing_is_exact_and_hash_safe() -> None:
    task_id = contract.parse_release_response(
        {"code": 200, "error": None, "data": {"task_id": "handler-task-01"}}
    )
    assert task_id == "handler-task-01"
    assert contract.parse_query_response(
        {
            "code": 200,
            "error": None,
            "data": [{"status": 0, "result": "[]"}],
        }
    ) == ("pending", None)
    result = json.dumps([{"status": 1, "file": "/v1/audio?path=private"}])
    assert contract.parse_query_response(
        {
            "code": 200,
            "error": None,
            "data": [{"status": 1, "result": result}],
        }
    ) == ("completed", "/v1/audio?path=private")


def test_provider_result_contains_exact_four_stems_without_private_text() -> None:
    artifact = {
        "url": "https://assets.example.test/object.wav?signature=private",
        "sha256": "1" * 64,
        "size_bytes": 192_044,
        "media_type": "audio/wav",
        "duration_seconds": 1.0,
        "sample_rate_hz": 48_000,
        "channels": 2,
    }
    result = contract.provider_result(
        image_digest=HANDLER_IMAGE_DIGEST,
        full_song=artifact,
        stems={stem: artifact for stem in contract.REQUIRED_STEMS},
    )
    assert set(result["stems"]) == {"vocals", "drums", "bass", "other"}
    assert result["raw_title_returned"] is False
    assert result["raw_lyrics_returned"] is False
    assert result["credential_returned"] is False


def test_dockerfile_is_immutable_offline_nonroot_and_model_baked() -> None:
    dockerfile = (HANDLER_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"FROM ghcr.io/ace-step/ace-step-1.5@{ACE_STEP_IMAGE_AMD64_DIGEST}" in dockerfile
    assert ":latest" not in dockerfile
    assert ACE_STEP_MODEL_REVISION in dockerfile
    assert ACE_STEP_LANGUAGE_MODEL_REVISION in dockerfile
    assert DEMUCS_CHECKPOINT_SHA256 in dockerfile
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert "TRANSFORMERS_OFFLINE=1" in dockerfile
    assert "USER aionex-song:aionex-song" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/python", "/opt/aionex-open-song/handler.py"]' in dockerfile
    requirements = (HANDLER_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert requirements.splitlines() == [
        "boto3==1.43.72",
        "demucs==4.0.1",
        "runpod==1.11.0",
    ]
