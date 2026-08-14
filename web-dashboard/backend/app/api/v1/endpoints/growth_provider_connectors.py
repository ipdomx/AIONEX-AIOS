from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.services import growth_provider_connectors as connectors

router = APIRouter(prefix="/provider-connectors")


class ValidationPreviewRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    capability: str = Field(min_length=1, max_length=80)
    mode: str = Field(min_length=1, max_length=32)
    credential_ref: str | None = Field(default=None, max_length=320)
    platform_approval: bool = False


@router.get("/catalog")
async def catalog(actor: UserRecord = Depends(current_user)) -> dict:
    return {
        "providers": connectors.connector_catalog(),
        "live_mutation_allowed": False,
        "real_spend_allowed": False,
    }


@router.post("/validate/preview")
async def preview_validation(
    payload: ValidationPreviewRequest,
    actor: UserRecord = Depends(current_user),
) -> dict:
    return connectors.validation_preview(
        payload.provider,
        payload.capability,
        payload.mode,
        payload.credential_ref,
        payload.platform_approval,
    )


@router.post("/{provider}/{capability}/contract-check")
async def contract_check(
    provider: str,
    capability: str,
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    if provider not in connectors.CONNECTORS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    row = await connectors.record_contract_evidence(
        session, provider, capability, actor.id
    )
    await session.commit()
    await session.refresh(row)
    return {
        "provider": row.provider,
        "capability": row.capability,
        "verification_state": row.verification_state,
        "evidence": row.evidence,
        "provider_call_allowed": False,
        "mutation_allowed": False,
        "spend_allowed": False,
    }
