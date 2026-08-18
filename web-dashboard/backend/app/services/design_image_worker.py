"""Phase 36E durable design-image provider worker.

The worker is fail-closed by default. It cannot claim or spend unless
DESIGN_IMAGE_LIVE_ENABLED is explicitly enabled by the operator.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.base import SessionLocal
from app.db.models import AIProvider, DesignImageExecution, MediaAssetEdge, MediaAssetNode
from app.services.ai_runtime_service import provider_credential, provider_enabled, validate_provider_base_url
from app.services.design_image_providers import (
    ProviderImageAdapter,
    ProviderImageFailure,
    ProviderImageInput,
    ProviderImageRequest,
    default_image_adapters,
)
from app.services.design_image_runtime import DesignImageClaim, DesignImageExecutionAuthority
from app.services.media_storage import MediaObjectStore, media_object_store

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedImageExecution:
    request: ProviderImageRequest
    credential: str
    base_url: str


def _now() -> datetime:
    return datetime.now(UTC)


class DesignImageWorker:
    def __init__(
        self,
        *,
        authority: DesignImageExecutionAuthority | None = None,
        store: MediaObjectStore | None = None,
        adapters: dict[str, ProviderImageAdapter] | None = None,
        worker_id: str | None = None,
    ) -> None:
        configured = (worker_id or settings.DESIGN_IMAGE_WORKER_ID).strip()
        self.worker_id = configured or f"design-image:{socket.gethostname()}"
        self.store = store or media_object_store()
        self.authority = authority or DesignImageExecutionAuthority(
            store=self.store,
            worker_id=self.worker_id,
            lease_seconds=int(settings.DESIGN_IMAGE_LEASE_SECONDS),
        )
        self.adapters = adapters or default_image_adapters(timeout_seconds=float(settings.DESIGN_IMAGE_PROVIDER_TIMEOUT_SECONDS))
        self.health_path = Path(settings.DESIGN_IMAGE_WORKER_HEALTH_FILE)
        self.cycles = 0
        self.errors = 0

    def write_health(self, status: str) -> None:
        payload = {
            "status": status,
            "worker_id": self.worker_id,
            "live_enabled": bool(settings.DESIGN_IMAGE_LIVE_ENABLED),
            "checked_at": _now().isoformat(),
            "checked_at_epoch": time.time(),
            "cycles": self.cycles,
            "errors": self.errors,
            "providers": sorted(self.adapters),
            "secret_returned": False,
        }
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.health_path.with_name(f".{self.health_path.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.health_path)

    async def preflight(self) -> None:
        await asyncio.to_thread(self.store.preflight)
        async with SessionLocal() as session:
            await session.execute(select(DesignImageExecution.id).limit(1))

    async def _load_execution(self, claim: DesignImageClaim) -> LoadedImageExecution:
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, claim.execution_id)
            if row is None or row.status != "running":
                raise ProviderImageFailure("execution_unavailable", retryable=False)
            target = await session.get(MediaAssetNode, row.target_node_id)
            if target is None or target.graph_id != row.graph_id or target.organization_id != row.organization_id:
                raise ProviderImageFailure("execution_scope", retryable=False)
            design = (target.prompt_metadata or {}).get("design_image")
            if not isinstance(design, dict):
                raise ProviderImageFailure("execution_prompt", retryable=False)
            prompt = str(design.get("compiled_prompt") or "").strip()
            if not prompt:
                raise ProviderImageFailure("execution_prompt", retryable=False)

            providers = list(
                (
                    await session.scalars(
                        select(AIProvider)
                        .where(
                            AIProvider.organization_id == settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID,
                            AIProvider.type == row.provider,
                            AIProvider.status == "connected",
                        )
                        .order_by(AIProvider.id)
                    )
                ).all()
            )
            if len(providers) != 1 or not provider_enabled(providers[0]):
                raise ProviderImageFailure("provider_authority", retryable=False)
            provider = providers[0]
            credential = provider_credential(provider)
            base_url = validate_provider_base_url(provider.type, provider.base_url)
            if not credential or not base_url:
                raise ProviderImageFailure("provider_unconfigured", retryable=False)

            parent_rows = list(
                (
                    await session.scalars(
                        select(MediaAssetNode)
                        .join(MediaAssetEdge, MediaAssetEdge.parent_node_id == MediaAssetNode.id)
                        .where(MediaAssetEdge.child_node_id == row.target_node_id)
                        .order_by(MediaAssetEdge.ordinal, MediaAssetNode.id)
                    )
                ).all()
            )
            parents: list[tuple[str, str, str]] = []
            for parent in parent_rows:
                if parent.status != "completed" or not parent.storage_key or not parent.media_type:
                    raise ProviderImageFailure("provider_input_missing", retryable=False)
                role = "mask" if parent.node_type == "mask" or (parent.operation_metadata or {}).get("design_role") == "mask" else "reference"
                parents.append((parent.storage_key, parent.media_type, role))

            options = dict(row.request_options or {})
            request = ProviderImageRequest(
                provider=row.provider,
                model=row.model,
                operation=row.operation,
                prompt=prompt,
                output_format=row.output_format,
                aspect_ratio=str(options.get("aspect_ratio") or "1:1"),
                image_size=str(options.get("image_size") or "1K"),
                quality=str(options.get("quality") or "auto"),
                background=str(options.get("background") or "auto"),
                options=options,
            )

        references: list[ProviderImageInput] = []
        mask: ProviderImageInput | None = None
        for key, content_type, role in parents:
            body = await asyncio.to_thread(self.store.get_bytes, key, max_bytes=settings.MEDIA_MAX_OBJECT_BYTES)
            item = ProviderImageInput(body=body, content_type=content_type, role=role)
            if role == "mask":
                if mask is not None:
                    raise ProviderImageFailure("provider_input_mask_count", retryable=False)
                mask = item
            else:
                references.append(item)
        return LoadedImageExecution(
            request=ProviderImageRequest(
                provider=request.provider,
                model=request.model,
                operation=request.operation,
                prompt=request.prompt,
                output_format=request.output_format,
                aspect_ratio=request.aspect_ratio,
                image_size=request.image_size,
                quality=request.quality,
                background=request.background,
                references=tuple(references),
                mask=mask,
                options=request.options,
            ),
            credential=credential,
            base_url=base_url,
        )

    async def run_once(self) -> bool:
        if not settings.DESIGN_IMAGE_LIVE_ENABLED:
            self.write_health("disabled")
            return False
        claim = await self.authority.claim()
        if claim is None:
            self.write_health("healthy")
            return False
        self.cycles += 1
        try:
            loaded = await self._load_execution(claim)
            adapter = self.adapters.get(loaded.request.provider)
            if adapter is None:
                raise ProviderImageFailure("provider_adapter_unavailable", retryable=False)
            result = await adapter.invoke(
                loaded.request, credential=loaded.credential, base_url=loaded.base_url
            )
            await self.authority.complete_bytes(
                claim,
                body=result.body,
                content_type=result.content_type,
                provider_request_id=result.request_id,
                provider_response_metadata=result.metadata,
                usage_metadata=result.usage,
                actual_cost_usd=result.actual_cost_usd,
            )
            self.write_health("healthy")
            return True
        except ProviderImageFailure as exc:
            self.errors += 1
            await self.authority.fail(
                claim,
                code=exc.code,
                message="Design image provider execution failed",
                permanent=not exc.retryable,
            )
            self.write_health("degraded")
            return True
        except Exception:
            self.errors += 1
            logger.exception("design image worker cycle failed", extra={"execution_id": claim.execution_id})
            await self.authority.fail(
                claim,
                code="design_image_worker_error",
                message="Design image worker execution failed",
                permanent=False,
            )
            self.write_health("degraded")
            return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(int(settings.DESIGN_IMAGE_POLL_SECONDS))


def healthcheck() -> int:
    path = Path(settings.DESIGN_IMAGE_WORKER_HEALTH_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload["checked_at_epoch"])
        status = str(payload.get("status") or "")
        return 0 if status in {"healthy", "disabled", "degraded"} and age <= 120 else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return healthcheck()
    setup_logging()
    asyncio.run(DesignImageWorker().run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
