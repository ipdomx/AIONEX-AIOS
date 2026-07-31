"""Firebase phone verification endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.firebase_phone import (
    issue_aios_phone_assertion,
    verify_firebase_phone_token,
)

router = APIRouter()


class FirebasePhoneAssertionRequest(BaseModel):
    id_token: str = Field(min_length=100, max_length=10000)
    phone_number: str = Field(
        min_length=8,
        max_length=20,
        pattern=r"^\+[1-9][0-9]{7,14}$",
    )


class FirebasePhoneAssertionResponse(BaseModel):
    phone_verification_token: str
    provider: str = "firebase"


@router.post("/firebase/assertion", response_model=FirebasePhoneAssertionResponse)
async def exchange_firebase_phone_token(
    data: FirebasePhoneAssertionRequest,
) -> FirebasePhoneAssertionResponse:
    claims = verify_firebase_phone_token(data.id_token, data.phone_number)
    assertion = issue_aios_phone_assertion(claims, data.phone_number)
    return FirebasePhoneAssertionResponse(phone_verification_token=assertion)
