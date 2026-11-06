"""Signed AIOS plan priority signal for the AIONEX AI gateway (roadmap 5.2).

Contract (``ipdomx/AIONEX-AI`` ``docs/workers/W02/2026-11-03-aios-plan-priority-and-warm-windows.md``):

* ``X-AIONEX-Plan``: ``free``, ``paid`` or ``owner``.
* ``X-AIONEX-Plan-Ts``: current Unix time in whole seconds.
* ``X-AIONEX-Plan-Sig``: lower-case hex
  ``HMAC_SHA256(secret, plan + "\\n" + ts + "\\n" + sha256_hex(body))``, where
  ``body`` is exactly the request bytes sent on the wire.

The shared secret is the content of the file named by
``AIONEX_AI_PLAN_SECRET_FILE`` with surrounding whitespace stripped (at least
16 bytes). Without a usable secret no header is sent and requests stay exactly
as before. The secret is re-read on every request so file rotation needs no
restart, and it is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PLAN_HEADER = "X-AIONEX-Plan"
PLAN_TS_HEADER = "X-AIONEX-Plan-Ts"
PLAN_SIG_HEADER = "X-AIONEX-Plan-Sig"
PLANS = frozenset({"free", "paid", "owner"})
AIONEX_AI_MODEL = "aionex-ai"
MIN_SECRET_BYTES = 16
_MAX_SECRET_FILE_BYTES = 4096

_current_plan: ContextVar[str | None] = ContextVar("aionex_ai_plan", default=None)


def is_aionex_ai_target(provider_type: str | None, model: str | None) -> bool:
    """True for the Ollama-compatible AIONEX AI route (``ollama:aionex-ai``)."""
    if str(provider_type or "").strip().lower() != "ollama":
        return False
    name = str(model or "").strip().lower()
    return name == AIONEX_AI_MODEL or name.startswith(AIONEX_AI_MODEL + ":")


def signing_enabled(provider_type: str | None, model: str | None) -> bool:
    """Cheap pre-check: an AIONEX AI target and a usable secret are both present."""
    return is_aionex_ai_target(provider_type, model) and read_plan_secret() is not None


def read_plan_secret(path: str | None = None) -> bytes | None:
    """Return the shared secret, or ``None`` when it is absent or unusable."""
    raw_path = str(settings.AIONEX_AI_PLAN_SECRET_FILE if path is None else path).strip()
    if not raw_path:
        return None
    source = Path(raw_path)
    try:
        if not source.is_file():
            return None
        with source.open("rb") as handle:
            data = handle.read(_MAX_SECRET_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_SECRET_FILE_BYTES:
        return None
    secret = data.strip()
    return secret if len(secret) >= MIN_SECRET_BYTES else None


def normalize_plan(value: str | None) -> str:
    plan = str(value or "").strip().lower()
    return plan if plan in PLANS else "free"


def plan_signature(secret: bytes, plan: str, ts: str, body: bytes) -> str:
    message = f"{plan}\n{ts}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret, message.encode("ascii"), hashlib.sha256).hexdigest()


def encode_json_body(payload: Any) -> bytes:
    """Serialize a JSON request body once; these exact bytes are signed and sent."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def plan_headers(
    body: bytes,
    *,
    plan: str | None = None,
    secret: bytes | None = None,
    now: float | None = None,
) -> dict[str, str]:
    """Signed plan headers for ``body``; empty when no secret is configured."""
    key = secret if secret is not None else read_plan_secret()
    if not key or len(key) < MIN_SECRET_BYTES:
        return {}
    value = normalize_plan(plan if plan is not None else _current_plan.get())
    ts = str(int(time.time() if now is None else now))
    return {
        PLAN_HEADER: value,
        PLAN_TS_HEADER: ts,
        PLAN_SIG_HEADER: plan_signature(key, value, ts, body),
    }


def signed_request(
    provider_type: str | None, model: str | None, payload: Any
) -> tuple[bytes | None, dict[str, str]]:
    """Return ``(raw_body, headers)`` for an AIONEX AI request.

    ``raw_body`` is ``None`` (send ``payload`` as before) unless headers were
    produced, so a missing secret keeps the request byte-for-byte unchanged.
    """
    if not is_aionex_ai_target(provider_type, model):
        return None, {}
    raw = encode_json_body(payload)
    headers = plan_headers(raw)
    if not headers:
        return None, {}
    return raw, headers


@contextmanager
def plan_context(plan: str | None) -> Iterator[None]:
    """Bind the caller's plan for AIONEX AI requests made in this context."""
    token = _current_plan.set(normalize_plan(plan) if plan is not None else None)
    try:
        yield
    finally:
        _current_plan.reset(token)


async def _plan_is_paid(session: AsyncSession, plan: Any) -> bool:
    from app.db.models import BillingPrice

    prices = (
        await session.scalars(select(BillingPrice).where(BillingPrice.plan_id == plan.id))
    ).all()
    return any(
        bool(price.enabled) and price.amount_minor is not None and int(price.amount_minor) > 0
        for price in prices
    )


async def resolve_plan(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str | None = None,
    role_name: str | None = None,
) -> str:
    """``owner`` for the Super Owner, ``paid`` for an active paid subscription, else ``free``.

    The subscription lookup is the one Security Lab entitlement uses
    (``security_entitlement.active_subscription_plan``).
    """
    from app.db.models import Role, User
    from app.services import security_entitlement

    role = role_name
    if role is None and user_id:
        role = await session.scalar(
            select(Role.name)
            .join(User, User.role_id == Role.id)
            .where(User.id == user_id, User.organization_id == organization_id)
        )
    if role == "Super Owner":
        return "owner"
    plan = await security_entitlement.active_subscription_plan(session, organization_id)
    if plan is not None and await _plan_is_paid(session, plan):
        return "paid"
    return "free"


async def plan_for_dispatch(
    session: AsyncSession,
    *,
    provider_type: str | None,
    model: str | None,
    organization_id: str,
    user_id: str | None = None,
    role_name: str | None = None,
) -> str | None:
    """Resolve the plan only when a signed AIONEX AI request will be made.

    Returns ``None`` (no lookup, no header) for other providers or when no
    secret is configured. A failed lookup downgrades to ``free`` — the same
    outcome the gateway applies to an invalid signature.
    """
    if not signing_enabled(provider_type, model):
        return None
    try:
        # A savepoint keeps the caller's transaction usable if the lookup fails.
        async with session.begin_nested():
            return await resolve_plan(
                session, organization_id=organization_id, user_id=user_id, role_name=role_name
            )
    except SQLAlchemyError as exc:
        logger.warning(
            "AIONEX AI plan lookup failed; sending free plan",
            error_type=type(exc).__name__,
        )
        return "free"
