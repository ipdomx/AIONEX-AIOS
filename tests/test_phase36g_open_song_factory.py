from __future__ import annotations

import pytest

from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_IMAGE_INDEX_DIGEST,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_TURBO_MODEL_REVISION,
    DEMUCS_CHECKPOINT_SHA256,
    OPEN_SONG_STEMS,
    RUNPOD_FLEX_A40_ROUTE,
    OpenSongFactoryError,
    OpenSongRequest,
    OpenSongRightsEvidence,
    build_open_song_plan,
)


def rights(
    *,
    basis: str = "original",
    evidence_sha256: str | None = None,
) -> OpenSongRightsEvidence:
    return OpenSongRightsEvidence(
        basis=basis,  # type: ignore[arg-type]
        commercial_use_authorized=True,
        provider_terms_accepted=True,
        ai_generated_disclosure_accepted=True,
        evidence_sha256=evidence_sha256,
    )


def request(**overrides: object) -> OpenSongRequest:
    values: dict[str, object] = {
        "title": "AIONEX Dawn",
        "concept": (
            "An original multilingual cinematic pop song with piano, strings, "
            "warm drums, a memorable chorus, and a clean resolved ending."
        ),
        "lyrics": (
            "[Verse]\nWe build the morning from a quiet spark,\n"
            "Across the sky we leave a hopeful mark.\n\n"
            "[Chorus]\nRise with the light, let every future start,\n"
            "A new horizon beating in the heart."
        ),
        "language": "en",
        "duration_seconds": 30,
        "bpm": 100,
        "musical_key": "Am",
        "rights": rights(),
        "time_signature": 4,
        "seed": 36,
    }
    values.update(overrides)
    return OpenSongRequest(**values)  # type: ignore[arg-type]


def test_open_song_plan_has_full_exit_gate_dag_and_pinned_supply_chain() -> None:
    plan = build_open_song_plan(request())
    assert plan.schema == "36G.open-song-plan.v1"
    assert plan.stems == ("vocals", "drums", "bass", "other")
    assert tuple(task.task_id for task in plan.tasks) == (
        "lyrics",
        "composition-vocals",
        "stems",
        "mix",
        "master",
        "waveform",
        "export",
    )
    assert plan.tasks[1].dependencies == ("lyrics",)
    assert plan.tasks[2].dependencies == ("composition-vocals",)
    assert plan.tasks[-1].dependencies == ("master", "waveform")
    assert ACE_STEP_IMAGE_INDEX_DIGEST.startswith("sha256:")
    assert ACE_STEP_IMAGE_AMD64_DIGEST.startswith("sha256:")
    assert len(ACE_STEP_MODEL_REVISION) == 40
    assert len(DEMUCS_CHECKPOINT_SHA256) == 64


def test_open_song_public_snapshot_is_hash_only_for_private_text() -> None:
    source = request()
    public = build_open_song_plan(source).public_snapshot()
    rendered = repr(public)
    assert source.title not in rendered
    assert source.concept not in rendered
    assert source.lyrics not in rendered
    assert public["private_title_returned"] is False
    assert public["private_concept_returned"] is False
    assert public["private_lyrics_returned"] is False
    assert public["generated_vocals"] is True
    assert public["stems_required"] is True
    assert public["stems"] == list(OPEN_SONG_STEMS)


def test_open_song_plan_is_deterministic_and_route_bound() -> None:
    first = build_open_song_plan(request())
    second = build_open_song_plan(request())
    preview = build_open_song_plan(
        request(), route_id="ace-step-official-space-acceptance"
    )
    assert first.checksum == second.checksum
    assert preview.checksum != first.checksum
    assert first.route.route_id == "runpod-flex-a40"
    assert preview.route.acceptance_only is True
    assert preview.route.model == "acestep-v15-turbo"
    assert preview.route.model_revision == ACE_STEP_TURBO_MODEL_REVISION
    assert preview.route.max_cost_usd == 0.0


def test_runpod_route_is_one_attempt_and_cap_bound() -> None:
    route = RUNPOD_FLEX_A40_ROUTE
    assert route.max_attempts == 1
    assert route.requires_positive_provider_balance is True
    assert route.rate_usd_per_second == 0.00034
    assert route.max_billed_seconds == 588
    assert route.rate_usd_per_second * route.max_billed_seconds <= route.max_cost_usd
    assert route.max_cost_usd == 0.20
    public = route.public_snapshot()
    assert public["automatic_retry"] is False
    assert public["automatic_cross_provider_fallback"] is False


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("concept", "Create this in the style of a famous singer and copy the voice.", "imitation"),
        ("duration_seconds", 181, "duration"),
        ("bpm", 221, "BPM"),
        ("musical_key", "H#", "key"),
        ("language", "english", "language"),
        ("output_profile_id", "mp3", "output profile"),
    ],
)
def test_open_song_rejects_unsafe_or_unsupported_requests(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(OpenSongFactoryError, match=match):
        request(**{field: value})


def test_non_original_lyrics_require_hash_evidence() -> None:
    with pytest.raises(OpenSongFactoryError, match="rights evidence"):
        rights(basis="licensed")
    accepted = rights(basis="licensed", evidence_sha256="a" * 64)
    assert accepted.public_snapshot()["evidence_present"] is True


def test_open_song_requires_commercial_terms_and_disclosure() -> None:
    with pytest.raises(OpenSongFactoryError, match="commercial"):
        OpenSongRightsEvidence(
            basis="original",
            commercial_use_authorized=False,
            provider_terms_accepted=True,
            ai_generated_disclosure_accepted=True,
        )
    with pytest.raises(OpenSongFactoryError, match="provider terms"):
        OpenSongRightsEvidence(
            basis="original",
            commercial_use_authorized=True,
            provider_terms_accepted=False,
            ai_generated_disclosure_accepted=True,
        )
    with pytest.raises(OpenSongFactoryError, match="disclosure"):
        OpenSongRightsEvidence(
            basis="original",
            commercial_use_authorized=True,
            provider_terms_accepted=True,
            ai_generated_disclosure_accepted=False,
        )


def test_runpod_runtime_binding_requires_distinct_handler_image_evidence() -> None:
    from aios.open_song_factory import OpenSongRuntimeBinding

    binding = OpenSongRuntimeBinding(
        route_id="runpod-flex-a40",
        endpoint_id_sha256="1" * 64,
        container_image_repository="ghcr.io/aionex/open-song-handler",
        container_image_index_digest="sha256:" + "2" * 64,
        container_image_digest="sha256:" + "3" * 64,
        image_sbom_sha256="4" * 64,
        handler_source_sha256="5" * 64,
    )
    public = binding.public_snapshot()
    assert public["runtime_image_verified"] is True
    assert public["endpoint_id_returned"] is False
    assert public["container_image_digest"] != ACE_STEP_IMAGE_AMD64_DIGEST
    with pytest.raises(OpenSongFactoryError, match="base image"):
        OpenSongRuntimeBinding(
            route_id="runpod-flex-a40",
            endpoint_id_sha256="1" * 64,
            container_image_repository="ghcr.io/aionex/open-song-handler",
            container_image_index_digest="sha256:" + "2" * 64,
            container_image_digest=ACE_STEP_IMAGE_AMD64_DIGEST,
            image_sbom_sha256="4" * 64,
            handler_source_sha256="5" * 64,
        )


def test_runpod_route_declares_audited_base_not_ready_handler_image() -> None:
    public = RUNPOD_FLEX_A40_ROUTE.public_snapshot()
    assert public["container_image_role"] == "audited-base"
    assert public["runtime_handler_image_binding_required"] is True
