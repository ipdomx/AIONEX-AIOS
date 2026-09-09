"""Bounded Owner input validation with no DNS or database access."""
from __future__ import annotations

from email_validator import EmailNotValidError, validate_email


def normalize_owner_user_email(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 254:
        raise ValueError("User email is invalid")
    try:
        return str(validate_email(value.strip().lower(), check_deliverability=False).normalized)
    except EmailNotValidError as exc:
        raise ValueError("User email is invalid") from exc
