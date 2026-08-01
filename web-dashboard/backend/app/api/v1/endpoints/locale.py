"""Locale evidence exposed without persisting precise location data."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _country_from_headers(request: Request) -> str | None:
    for key in ("cf-ipcountry", "x-country-code", "x-vercel-ip-country"):
        value = request.headers.get(key)
        if value:
            normalized = value.strip().upper()
            if len(normalized) == 2 and normalized.isalpha() and normalized != "XX":
                return normalized
    return None


def _accept_languages(request: Request) -> list[str]:
    header = request.headers.get("accept-language", "")
    values: list[str] = []
    for item in header.split(","):
        locale = item.split(";", 1)[0].strip()
        if locale and locale not in values:
            values.append(locale[:35])
    return values[:10]


@router.get("/context")
async def locale_context(request: Request) -> dict[str, object]:
    """Return coarse signals only; raw IP addresses are never returned."""

    return {
        "ip_country": _country_from_headers(request),
        "accept_languages": _accept_languages(request),
        "country_source": "trusted-proxy-header" if _country_from_headers(request) else None,
    }
