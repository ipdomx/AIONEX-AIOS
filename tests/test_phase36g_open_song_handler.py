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
sys.modules["contract"] = contract
HANDLER_SPEC = importlib.util.spec_from_file_location(
    "aionex_open_song_handler_runtime", HANDLER_ROOT / "handler.py"
)
assert HANDLER_SPEC is not None and HANDLER_SPEC.loader is not None
handler_runtime = importlib.util.module_from_spec(HANDLER_SPEC)
sys.modules[HANDLER_SPEC.name] = handler_runtime
HANDLER_SPEC.loader.exec_module(handler_runtime)

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
        "artifact_id": "a" * 48,
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
    assert "ACESTEP_PROJECT_ROOT=/app" in dockerfile
    assert "ACESTEP_CHECKPOINTS_DIR=/app/checkpoints" in dockerfile
    assert "ACESTEP_TMPDIR=/tmp/aionex-open-song/acestep-tmp" in dockerfile
    assert "TRITON_CACHE_DIR=/tmp/aionex-open-song/triton" in dockerfile
    assert "TORCHINDUCTOR_CACHE_DIR=/tmp/aionex-open-song/torchinductor" in dockerfile
    assert "XDG_CACHE_HOME=/tmp/aionex-open-song/xdg-cache" in dockerfile
    assert "HF_HOME=/tmp/aionex-open-song/hf-cache" in dockerfile
    assert "MPLCONFIGDIR=/tmp/aionex-open-song/matplotlib" in dockerfile
    assert "install -d -m 0700 -o aionex-song -g aionex-song /app/.cache/acestep" in dockerfile
    assert "aionex-song:aionex-song:700" in dockerfile
    assert "USER aionex-song:aionex-song" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/python", "/opt/aionex-open-song/handler.py"]' in dockerfile
    requirements = (HANDLER_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert requirements.splitlines() == [
        "demucs==4.0.1",
        "runpod==1.11.0",
    ]
    handler_source = (HANDLER_ROOT / "handler.py").read_text(encoding="utf-8")
    assert "S3ArtifactPublisher" not in handler_source
    assert "AionexArtifactBridgePublisher" in handler_source
    assert "AIONEX_ARTIFACT_S3_" not in handler_source
    verify_source = (HANDLER_ROOT / "verify_runtime.py").read_text(encoding="utf-8")
    assert "boto3" not in verify_source
    assert 'version("demucs") == "4.0.1"' in verify_source
    assert 'version("runpod") == "1.11.0"' in verify_source
    assert 'version("diffusers") == "0.38.0"' in verify_source
    assert 'version("orjson") == "3.11.6"' in verify_source
    assert 'version("pillow") == "12.3.0"' in verify_source
    assert 'version("python-multipart") == "0.0.30"' in verify_source
    assert 'version("starlette") == "1.3.1"' in verify_source
    assert 'shutil.which("uv") is None' in verify_source
    assert "linux-libc-dev" in dockerfile
    assert "apt-get purge -y" in dockerfile
    assert "diffusers==0.38.0" in dockerfile
    assert "pillow==12.3.0" in dockerfile
    assert "python-multipart==0.0.30" in dockerfile
    assert "starlette==1.3.1" in dockerfile
    assert "rm -f /usr/bin/uv /usr/bin/uvx" in dockerfile

def test_open_song_vex_is_package_scoped_and_exact() -> None:
    document = json.loads((HANDLER_ROOT / "openvex.json").read_text(encoding="utf-8"))
    assert document["@context"] == "https://openvex.dev/ns/v0.2.0"
    statements = document["statements"]
    assert len(statements) == 12
    expected_counts = {
        "CVE-2022-42919": 6,
        "CVE-2026-31253": 1,
        "CVE-2026-28414": 1,
        "CVE-2026-28416": 1,
        "CVE-2026-48545": 1,
        "CVE-2026-4372": 1,
        "CVE-2026-5241": 1,
    }
    observed: dict[str, int] = {}
    for statement in statements:
        vulnerability = statement["vulnerability"]["name"]
        observed[vulnerability] = observed.get(vulnerability, 0) + 1
        assert statement["status"] == "not_affected"
        assert len(statement["impact_statement"]) >= 40
        assert len(statement["products"]) == 1
        product = statement["products"][0]["@id"]
        assert product.startswith("pkg:") and "@" in product and "*" not in product
    assert observed == expected_counts


def test_artifact_bridge_publisher_keeps_grant_out_of_url_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_id = "e" * 48
    upload_token = "1800000600:" + "f" * 64
    target = {
        "artifact_id": artifact_id,
        "upload_url": f"https://api.vip-e.net/api/v1/audio-song-artifacts/{artifact_id}",
        "upload_token": upload_token,
    }
    raw = payload()
    raw["artifact_bridge"] = {
        "schema": "aionex.open-song-artifact-bridge.v1",
        "artifacts": {key: dict(target) for key in ("full_song", "vocals", "drums", "bass", "other")},
    }
    monkeypatch.setenv("AIONEX_ARTIFACT_BRIDGE_ALLOWED_HOST", "api.vip-e.net")
    observed: dict[str, object] = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, maximum: int) -> bytes:
            assert maximum == 65_536
            return b"{}"

    class Opener:
        def open(self, request, timeout: int):
            observed["request"] = request
            observed["timeout"] = timeout
            return Response()

    monkeypatch.setattr(handler_runtime.urllib.request, "build_opener", lambda *_: Opener())
    publisher = handler_runtime.AionexArtifactBridgePublisher(raw)
    result = publisher.publish(wav_file(tmp_path), logical_key="full_song")
    request = observed["request"]
    assert request.full_url == target["upload_url"]
    assert request.get_method() == "POST"
    assert upload_token not in request.full_url
    assert request.get_header("Authorization") == f"Bearer {upload_token}"
    assert result["artifact_id"] == artifact_id
    assert "url" not in result
    assert "upload_token" not in result


def test_artifact_bridge_rejects_host_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_id = "e" * 48
    raw = payload()
    raw["artifact_bridge"] = {
        "schema": "aionex.open-song-artifact-bridge.v1",
        "artifacts": {
            key: {
                "artifact_id": artifact_id,
                "upload_url": f"https://evil.example/api/v1/audio-song-artifacts/{artifact_id}",
                "upload_token": "1800000600:" + "f" * 64,
            }
            for key in ("full_song", "vocals", "drums", "bass", "other")
        },
    }
    monkeypatch.setenv("AIONEX_ARTIFACT_BRIDGE_ALLOWED_HOST", "api.vip-e.net")
    with pytest.raises(handler_runtime.OpenSongHandlerRuntimeError, match="upload URL"):
        handler_runtime.AionexArtifactBridgePublisher(raw)


def test_ace_step_health_requires_exact_initialized_model_pair() -> None:
    ready = {
        "code": 200,
        "error": None,
        "data": {
            "status": "ok",
            "service": "ACE-Step API",
            "models_initialized": True,
            "llm_initialized": True,
            "loaded_model": "acestep-v15-base",
            "loaded_lm_model": "acestep-5Hz-lm-4B",
        },
    }
    assert handler_runtime._ace_step_health_ready(ready) is True
    for key in ("models_initialized", "llm_initialized"):
        value = json.loads(json.dumps(ready))
        value["data"][key] = False
        assert handler_runtime._ace_step_health_ready(value) is False
    wrong_model = json.loads(json.dumps(ready))
    wrong_model["data"]["loaded_model"] = "acestep-v15-turbo"
    assert handler_runtime._ace_step_health_ready(wrong_model) is False
    wrong_lm = json.loads(json.dumps(ready))
    wrong_lm["data"]["loaded_lm_model"] = "acestep-5Hz-lm-1.7B"
    assert handler_runtime._ace_step_health_ready(wrong_lm) is False
    assert handler_runtime._ace_step_health_ready({"code": 200, "data": {"status": "ok"}}) is False


def test_handler_uses_current_ace_step_eager_init_environment_contract() -> None:
    source = (HANDLER_ROOT / "handler.py").read_text(encoding="utf-8")
    dockerfile = (HANDLER_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"ACESTEP_LM_BACKEND": "pt"' in source
    assert '"ACESTEP_NO_INIT": "false"' in source
    assert '"ACESTEP_INIT_LLM": "true"' in source
    assert "ACESTEP_LLM_BACKEND" not in source
    assert "ACESTEP_INIT_SERVICE" not in source
    assert "ACESTEP_LM_BACKEND=pt" in dockerfile
    assert "ACESTEP_NO_INIT=false" in dockerfile
    assert "ACESTEP_INIT_LLM=true" in dockerfile
    assert "ACESTEP_LLM_BACKEND" not in dockerfile
    assert "ACE_STEP_MAIN_MODEL_REVISION=19671f406d603126926c1b7e2adc169acbcade22" in dockerfile
    assert "patch_acestep_runtime.py" in dockerfile
    selected_prepare = (HANDLER_ROOT / "prepare_models.py").read_text(encoding="utf-8")
    shared_prepare = (HANDLER_ROOT / "prepare_shared_models.py").read_text(encoding="utf-8")
    assert "19671f406d603126926c1b7e2adc169acbcade22" in shared_prepare
    assert '"vae/*"' in shared_prepare
    assert '"Qwen3-Embedding-0.6B/*"' in shared_prepare
    assert "ACE-Step/Ace-Step1.5" not in selected_prepare
    assert "prepare_shared_models.py" in dockerfile
    patch_source = (HANDLER_ROOT / "patch_acestep_runtime.py").read_text(encoding="utf-8")
    assert "02a95f2293dc0cd82ff5046816503668f8339157ba0b18715e061f3142999f8f" in patch_source
    assert "Required Qwen3 text encoder is unavailable" in patch_source
    assert "Required official VAE is unavailable" in patch_source
    demucs_patch = (HANDLER_ROOT / "patch_demucs_runtime.py").read_text(encoding="utf-8")
    assert "37375543dad61a7dc549caf6f165c0500d903313159c70cf893d47718194b865" in demucs_patch
    assert "weights_only=False" in demucs_patch
    assert "patch_demucs_runtime.py" in dockerfile
    assert "LocalRepo(Path('/opt/aionex-demucs-models')).get_model('955717e8')" in dockerfile


def test_handler_failure_codes_are_stage_specific_and_sanitized() -> None:
    cases = {
        "ACE-Step API exited during startup": "acestep_api_startup_exit",
        "ACE-Step generation failed": "acestep_generation_failed",
        "ACE-Step canonicalization failed": "acestep_canonicalization_failed",
        "Demucs separation failed": "demucs_separation_failed",
        "artifact bridge upload failed": "artifact_upload_failed",
    }
    for message, expected in cases.items():
        exc = handler_runtime.OpenSongHandlerRuntimeError(message)
        assert handler_runtime._safe_failure_code(exc) == expected
        assert message not in expected
    assert handler_runtime._safe_failure_code(
        contract.OpenSongHandlerContractError("title is invalid")
    ) == "contract_invalid"
    assert handler_runtime._safe_failure_code(
        handler_runtime.OpenSongHandlerRuntimeError("unmapped internal detail")
    ) == "runtime_unclassified"
