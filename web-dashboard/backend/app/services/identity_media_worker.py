"""Durable Replicate identity-media worker."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    ReplicateFile,
    ReplicateIdentityMediaAdapter,
    issue_provider_input_token,
    provider_input_url,
)
from app.services.identity_media_runtime import (
    IdentityMediaClaim,
    claim_next,
    complete_execution,
    fail_execution,
    load_claim,
    record_primary_submission,
    record_secondary_submission,
    release_for_poll,
)
from app.services.media_storage import MediaObjectStore, media_object_store

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _content_suffix(content_type: str, *, kind: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
    }
    return mapping.get(content_type, ".bin" if kind != "video" else ".mp4")


def _output_media(operation: str, body: bytes, content_type: str) -> tuple[str, str]:
    media = content_type.lower().split(";", 1)[0].strip()
    if operation == "voice_clone":
        if media.startswith("audio/"):
            return media, ".mp3" if media == "audio/mpeg" else ".wav" if "wav" in media else ".audio"
        if body.startswith(b"ID3") or (len(body) > 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0):
            return "audio/mpeg", ".mp3"
        if body.startswith(b"RIFF") and body[8:12] == b"WAVE":
            return "audio/wav", ".wav"
        raise IdentityMediaProviderFailure("provider_audio_envelope_rejected")
    if len(body) < 12 or body[4:8] != b"ftyp":
        raise IdentityMediaProviderFailure("provider_video_envelope_rejected")
    return "video/mp4", ".mp4"


def _voice_id(output: Any) -> str:
    if not isinstance(output, dict):
        raise IdentityMediaProviderFailure("provider_voice_clone_output_invalid")
    value = str(output.get("voice_id") or "").strip()
    if not value or len(value) > 200:
        raise IdentityMediaProviderFailure("provider_voice_clone_output_invalid")
    return value


def _output_url(output: Any) -> Any:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and len(output) == 1:
        return output[0]
    raise IdentityMediaProviderFailure("provider_output_invalid")


class IdentityMediaWorker:
    def __init__(
        self,
        *,
        store: MediaObjectStore | None = None,
        adapter: ReplicateIdentityMediaAdapter | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = str(worker_id or settings.IDENTITY_MEDIA_WORKER_ID or "").strip()
        self.worker_id = configured or f"identity-media:{socket.gethostname()}"
        credential = str(settings.REPLICATE_API_TOKEN or "").strip()
        self.adapter = adapter or ReplicateIdentityMediaAdapter(
            credential,
            timeout_seconds=float(settings.IDENTITY_MEDIA_PROVIDER_TIMEOUT_SECONDS),
            max_download_bytes=int(settings.IDENTITY_MEDIA_MAX_PROVIDER_BYTES),
        )
        self.store = store or media_object_store()
        self.poll_seconds = int(settings.IDENTITY_MEDIA_POLL_SECONDS)
        self.lease_seconds = int(settings.IDENTITY_MEDIA_LEASE_SECONDS)
        self.health_file = Path(settings.IDENTITY_MEDIA_WORKER_HEALTH_FILE)

    def health(self, *, status: str = "healthy", error: str | None = None) -> None:
        payload = {
            "status": status,
            "worker": self.worker_id,
            "live_enabled": bool(settings.IDENTITY_MEDIA_LIVE_ENABLED),
            "provider": "replicate",
            "updated_at": _now().isoformat(),
            "error": error,
            "raw_credentials_returned": False,
        }
        self.health_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.health_file.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.health_file)

    async def _input_file(self, row, name: str):
        keys = dict(row.input_storage_keys or {})
        key = str(keys.get(name) or "").strip()
        if not key:
            return None
        payload = dict(row.request_payload or {})
        types = dict(payload.get("input_content_types") or {})
        filenames = dict(payload.get("input_filenames") or {})
        content_type = str(types.get(name) or "application/octet-stream").strip().lower()
        filename = str(filenames.get(name) or f"{name}{_content_suffix(content_type, kind=name)}")[:160]
        body = await asyncio.to_thread(
            self.store.get_bytes,
            key,
            max_bytes=min(int(settings.IDENTITY_MEDIA_MAX_PROVIDER_BYTES), 100 * 1024 * 1024),
        )
        if row.operation == "voice_clone" and name == "audio":
            token = issue_provider_input_token(
                execution_id=row.id,
                input_name=name,
                secret=settings.SECRET_KEY,
                ttl_seconds=900,
            )
            return ReplicateFile(
                file_id="signed-provider-input",
                url=provider_input_url(
                    settings.PORTAL_PUBLIC_API_ORIGIN,
                    token,
                    filename,
                ),
            )
        return await self.adapter.upload_private_file(
            body=body,
            filename=filename,
            content_type=content_type,
        )

    async def _submit(self, claim: IdentityMediaClaim) -> None:
        async with SessionLocal() as session:
            row = await load_claim(session, claim)
            if row is None:
                return
            operation = row.operation
            payload = dict(row.request_payload or {})
            if row.provider_job_id:
                await session.rollback()
                return
            metadata: dict[str, Any]
            try:
                if operation == "voice_clone":
                    audio = await self._input_file(row, "audio")
                    if audio is None:
                        raise IdentityMediaProviderFailure("identity_media_audio_required")
                    prediction = await self.adapter.create_prediction(
                        model="minimax/voice-cloning",
                        inputs={
                            "voice_file": audio.url,
                            "model": "speech-02-hd",
                            "need_noise_reduction": True,
                            "need_volume_normalization": True,
                        },
                        cancel_after_seconds=600,
                    )
                    metadata = {"stage": "voice_clone", "uploaded_file_ids": [audio.file_id]}
                elif operation in {"talking_head", "face_reenactment", "avatar_generation"}:
                    image = await self._input_file(row, "image")
                    if image is None:
                        raise IdentityMediaProviderFailure("identity_media_image_required")
                    audio = await self._input_file(row, "audio")
                    inputs: dict[str, Any] = {
                        "image": image.url,
                        "resolution": "720p",
                        "video_prompt": str(payload.get("video_prompt") or "The person is talking naturally.")[:1000],
                        "disable_safety_filter": False,
                        "disable_prompt_upsampling": False,
                        "negative_prompt": "watermark, subtitles, scene change, blurry, low quality",
                    }
                    file_ids = [image.file_id]
                    if audio is not None:
                        inputs["audio"] = audio.url
                        file_ids.append(audio.file_id)
                    else:
                        script = str(payload.get("script") or "").strip()
                        if not script:
                            raise IdentityMediaProviderFailure("identity_media_script_or_audio_required")
                        inputs["voice_script"] = script[:5000]
                    prediction = await self.adapter.create_prediction(
                        model="prunaai/p-video-avatar",
                        inputs=inputs,
                        cancel_after_seconds=900,
                    )
                    metadata = {"stage": "avatar_video", "uploaded_file_ids": file_ids, "safety_filter_forced": True}
                elif operation == "lip_sync":
                    video = await self._input_file(row, "video")
                    audio = await self._input_file(row, "audio")
                    if video is None or audio is None:
                        raise IdentityMediaProviderFailure("identity_media_video_audio_required")
                    prediction = await self.adapter.create_prediction(
                        model="sync/lipsync-2",
                        inputs={
                            "video": video.url,
                            "audio": audio.url,
                            "sync_mode": "loop",
                            "temperature": 0.5,
                            "active_speaker": False,
                        },
                        cancel_after_seconds=900,
                    )
                    metadata = {"stage": "lip_sync", "uploaded_file_ids": [video.file_id, audio.file_id]}
                else:
                    raise IdentityMediaProviderFailure("identity_media_runtime_pending")
                await record_primary_submission(
                    session,
                    claim,
                    provider_job_id=prediction.prediction_id,
                    provider_state=prediction.status,
                    provider_metadata=metadata,
                    poll_after_seconds=self.poll_seconds,
                )
                await session.commit()
            except IdentityMediaProviderFailure as exc:
                await fail_execution(
                    session,
                    claim,
                    code=exc.code,
                    message="Identity media provider submission failed",
                    needs_review=exc.ambiguous_submission,
                )
                await session.commit()

    async def _poll_voice_clone(self, session, row, claim: IdentityMediaClaim) -> None:
        if row.secondary_provider_job_id:
            prediction = await self.adapter.get_prediction(row.secondary_provider_job_id)
            if prediction.status in {"starting", "processing"}:
                await release_for_poll(session, claim, provider_state=prediction.status, metrics=prediction.metrics, poll_after_seconds=self.poll_seconds)
                return
            if prediction.status != "succeeded":
                await fail_execution(session, claim, code="provider_secondary_failed", message="Generated cloned speech failed")
                return
            body, content_type = await self.adapter.download_output(_output_url(prediction.output))
            media_type, suffix = _output_media("voice_clone", body, content_type)
            key = f"identity-media/{row.organization_id}/{row.id}/output{suffix}"
            stored = await asyncio.to_thread(self.store.put_bytes, key, body, media_type, metadata={"execution": row.id})
            await complete_execution(
                session,
                claim,
                storage_backend=stored.backend,
                storage_key=stored.key,
                checksum=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type=media_type,
                actual_cost_usd=None,
                provider_metadata={"secondary_metrics": prediction.metrics},
            )
            return

        prediction = await self.adapter.get_prediction(row.provider_job_id)
        if prediction.status in {"starting", "processing"}:
            await release_for_poll(session, claim, provider_state=prediction.status, metrics=prediction.metrics, poll_after_seconds=self.poll_seconds)
            return
        if prediction.status != "succeeded":
            await fail_execution(session, claim, code="provider_voice_clone_failed", message="Voice cloning provider execution failed")
            return
        voice_id = _voice_id(prediction.output)
        text = str((row.request_payload or {}).get("script") or "").strip()
        if not text:
            await fail_execution(session, claim, code="identity_media_script_required", message="Cloned speech script is missing")
            return
        try:
            secondary = await self.adapter.create_prediction(
                model="minimax/speech-02-hd",
                inputs={
                    "text": text[:10000],
                    "voice_id": voice_id,
                    "audio_format": "mp3",
                    "sample_rate": 32000,
                    "channel": "mono",
                    "speed": 1.0,
                    "emotion": "auto",
                },
                cancel_after_seconds=600,
            )
        except IdentityMediaProviderFailure as exc:
            await fail_execution(
                session,
                claim,
                code=exc.code,
                message="Cloned speech submission failed",
                needs_review=exc.ambiguous_submission,
            )
            return
        await record_secondary_submission(
            session,
            claim,
            provider_job_id=secondary.prediction_id,
            provider_state=secondary.status,
            provider_metadata={"stage": "cloned_speech", "voice_id_returned_to_client": False},
            poll_after_seconds=self.poll_seconds,
        )

    async def _poll(self, claim: IdentityMediaClaim) -> None:
        async with SessionLocal() as session:
            row = await load_claim(session, claim)
            if row is None:
                return
            if not row.provider_job_id:
                await fail_execution(session, claim, code="provider_job_missing", message="Provider job identity is missing", needs_review=True)
                await session.commit()
                return
            try:
                if row.operation == "voice_clone":
                    await self._poll_voice_clone(session, row, claim)
                    await session.commit()
                    return
                prediction = await self.adapter.get_prediction(row.provider_job_id)
                if prediction.status in {"starting", "processing"}:
                    await release_for_poll(session, claim, provider_state=prediction.status, metrics=prediction.metrics, poll_after_seconds=self.poll_seconds)
                    await session.commit()
                    return
                if prediction.status != "succeeded":
                    await fail_execution(session, claim, code="provider_execution_failed", message="Identity media provider execution failed")
                    await session.commit()
                    return
                body, content_type = await self.adapter.download_output(_output_url(prediction.output))
                media_type, suffix = _output_media(row.operation, body, content_type)
                key = f"identity-media/{row.organization_id}/{row.id}/output{suffix}"
                stored = await asyncio.to_thread(self.store.put_bytes, key, body, media_type, metadata={"execution": row.id})
                await complete_execution(
                    session,
                    claim,
                    storage_backend=stored.backend,
                    storage_key=stored.key,
                    checksum=stored.sha256,
                    size_bytes=stored.size_bytes,
                    media_type=media_type,
                    actual_cost_usd=None,
                    provider_metadata={"metrics": prediction.metrics, "safety_filter_forced": row.model == "prunaai/p-video-avatar"},
                )
                await session.commit()
            except IdentityMediaProviderFailure as exc:
                await fail_execution(
                    session,
                    claim,
                    code=exc.code,
                    message="Identity media provider polling or output validation failed",
                    needs_review=exc.ambiguous_submission,
                )
                await session.commit()

    async def cycle(self) -> bool:
        if not settings.IDENTITY_MEDIA_LIVE_ENABLED:
            self.health(status="disabled")
            return False
        async with SessionLocal() as session:
            claim = await claim_next(
                session,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            await session.commit()
        if claim is None:
            self.health()
            return False
        try:
            if claim.mode == "submit":
                await self._submit(claim)
            else:
                await self._poll(claim)
            self.health()
        except Exception as exc:
            logger.exception("identity media worker cycle failed", extra={"error_type": type(exc).__name__})
            async with SessionLocal() as session:
                await fail_execution(session, claim, code="identity_media_worker_error", message="Identity media worker execution failed", needs_review=True)
                await session.commit()
            self.health(status="degraded", error=type(exc).__name__)
        return True

    async def run(self) -> None:
        self.health(status="starting")
        while True:
            worked = await self.cycle()
            if not worked:
                await asyncio.sleep(self.poll_seconds)


def _healthcheck() -> int:
    path = Path(settings.IDENTITY_MEDIA_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(str(payload["updated_at"]).replace("Z", "+00:00"))
        age = (_now() - updated.astimezone(UTC)).total_seconds()
        return 0 if payload.get("status") in {"healthy", "disabled", "starting"} and age < 180 else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(_healthcheck())
    setup_logging()
    asyncio.run(IdentityMediaWorker().run())


if __name__ == "__main__":
    main()
