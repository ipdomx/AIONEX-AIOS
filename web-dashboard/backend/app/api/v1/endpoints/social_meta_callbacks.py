"""Public Meta callbacks under /api/v1/social/meta (roadmap 3.6 and 3.8).

* ``GET  /meta/webhooks``: the subscription verify challenge.
* ``POST /meta/webhooks``: Page ``feed``/``messages`` and Instagram
  ``comments``/``messages`` changes, accepted only with a valid
  ``X-Hub-Signature-256``; each change is applied once (idempotency ledger).
* ``POST /meta/deauthorize`` and ``POST /meta/data-deletion``: Meta's signed
  ``signed_request`` callbacks; they delete the person's tokens (and, for
  deletion, their inbox data) and return the confirmation URL and code.
* ``GET  /meta/data-deletion/status``: the public status behind that URL.

These routes are reached by Meta's servers or by an anonymous browser, so
they trust nothing but the signature or the random confirmation code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import social as social_api
from app.core.logging import get_logger
from app.db.base import get_db
from app.db.models import SocialWebhookEvent
from app.services import social_data_deletion as deletion
from app.services import social_inbox as inbox
from app.services import social_meta_webhooks as webhooks
from app.services.social_connectors import SocialConnectorError

router = APIRouter()
logger = get_logger(__name__)


def _no_store(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    return response


async def _body(request: Request, *, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "payload-too-large", "message": "payload too large"},
            )
    return bytes(body)


@router.get("/meta/webhooks", include_in_schema=False)
async def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode", max_length=32),
    token: str | None = Query(default=None, alias="hub.verify_token", max_length=512),
    challenge: str | None = Query(default=None, alias="hub.challenge", max_length=256),
) -> PlainTextResponse:
    try:
        value = webhooks.verify_challenge(mode, token, challenge)
    except SocialConnectorError as exc:
        raise social_api._error(exc) from exc
    return _no_store(PlainTextResponse(value))


@router.post("/meta/webhooks", include_in_schema=False)
async def receive_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    body = await _body(request, limit=webhooks.MAX_BODY_BYTES)
    try:
        webhooks.verify_signature(body, request.headers.get("x-hub-signature-256"))
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SocialConnectorError("webhook-payload-invalid", status_code=400) from None
        changes = webhooks.parse_payload(payload)
    except SocialConnectorError as exc:
        raise social_api._error(exc) from exc
    applied = duplicates = 0
    try:
        for change in changes:
            ledger = await session.scalar(
                pg_insert(SocialWebhookEvent)
                .values(
                    provider="meta",
                    event_key=change.event_key,
                    object_type=change.object_type,
                    field=change.field,
                    entry_ref=change.entry_ref,
                    outcome="received",
                    matched_accounts=0,
                    received_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="uq_social_webhook_events_key")
                .returning(SocialWebhookEvent.id)
            )
            if ledger is None:
                duplicates += 1
                continue
            row = await session.get(SocialWebhookEvent, ledger)
            if row is None:
                raise RuntimeError("webhook ledger row vanished inside its transaction")
            if change.item is None:
                row.outcome = "ignored"
                continue
            matched, stored = await inbox.ingest_items(session, [change.item], source="webhook")
            row.matched_accounts = matched
            row.outcome = "stored" if stored else ("unmatched" if not matched else "unchanged")
            applied += stored
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Meta retries a non-2xx delivery, so a failed change is not lost.
        logger.error("Meta webhook processing failed", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "webhook-processing-failed", "message": "retry later"},
        ) from None
    return _no_store(
        JSONResponse({"received": len(changes), "applied": applied, "duplicates": duplicates})
    )


async def _signed_callback(request: Request, session: AsyncSession, kind: str) -> dict[str, Any]:
    body = await _body(request, limit=webhooks.MAX_SIGNED_REQUEST * 2)
    try:
        form = parse_qs(body.decode("utf-8"), max_num_fields=10)
    except (UnicodeDecodeError, ValueError):
        form = {}
    values = form.get("signed_request") or []
    signed = values[0] if values else None
    try:
        payload = webhooks.parse_signed_request(signed)
        outcome = await deletion.handle_callback(
            session, kind=kind, meta_user_id=str(payload["user_id"])
        )
        await session.commit()
    except SocialConnectorError as exc:
        await session.rollback()
        raise social_api._error(exc) from exc
    return {"url": outcome.url, "confirmation_code": outcome.confirmation_code}


@router.post("/meta/deauthorize", include_in_schema=False)
async def deauthorize(request: Request, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    result = await _signed_callback(request, session, "deauthorize")
    return _no_store(JSONResponse({"success": True, **result}))


@router.post("/meta/data-deletion", include_in_schema=False)
async def data_deletion(request: Request, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    # Meta expects exactly {"url": ..., "confirmation_code": ...}.
    return _no_store(JSONResponse(await _signed_callback(request, session, "deletion")))


@router.get("/meta/data-deletion/status")
async def data_deletion_status(
    code: str = Query(min_length=8, max_length=32),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        result = await deletion.status(session, code)
    except SocialConnectorError as exc:
        raise social_api._error(exc) from exc
    return _no_store(JSONResponse(jsonable_encoder(result)))
