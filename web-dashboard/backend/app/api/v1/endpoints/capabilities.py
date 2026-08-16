"""Public capability manifests used by onboarding and project setup."""

from __future__ import annotations

from app.api.v1.endpoints import studio
from app.services.programming_languages import programming_language_manifest
from aios.phase36_program import phase36_program_snapshot
from fastapi import APIRouter

router = APIRouter()
router.include_router(studio.router, prefix="/studio", tags=["Production Studio"])


@router.get("/programming-languages")
async def programming_languages() -> dict[str, object]:
    languages = programming_language_manifest()
    return {
        "count": len(languages),
        "languages": languages,
        "execution_policy": (
            "Source generation and analysis are available through governed AI providers. "
            "Execution requires an isolated runner configured for the selected language."
        ),
    }


@router.get("/phase36")
async def phase36_capabilities() -> dict[str, object]:
    """Public, non-secret product maturity snapshot for the current expansion contract."""
    return phase36_program_snapshot()
