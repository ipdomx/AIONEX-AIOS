from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import GrowthSocialProviderCapability

TELEGRAM_PROVIDER = "telegram"
TELEGRAM_CAPABILITY = "account.read"
TELEGRAM_SCOPE = "owner_bots"
TELEGRAM_VALIDATION_MODE = "read_only"
ADMIN_TOKEN_FILE_ENV = "AIOS_TELEGRAM_BOT_TOKEN_FILE"
USER_TOKEN_FILE_ENV = "AIOS_USER_TELEGRAM_BOT_TOKEN_FILE"
ADMIN_CREDENTIAL_REF = "secretref://file/telegram/admin-bot-token"
USER_CREDENTIAL_REF = "secretref://file/telegram/user-bot-token"
_ALLOWED_SECRET_PREFIX = "/run/operator-secrets/"


class TelegramReadOnlyValidationError(RuntimeError):
    """Fail-closed Telegram Bot API read-only validation error."""


def _safe_token_file(env_name: str) -> str:
    token_file = os.environ.get(env_name, "").strip()
    if not token_file.startswith(_ALLOWED_SECRET_PREFIX):
        raise TelegramReadOnlyValidationError(
            f"telegram-token-file-not-allowlisted:{env_name.lower()}"
        )
    return token_file


def _read_token(token_file: str) -> str:
    path = Path(token_file)
    if not path.is_file():
        raise TelegramReadOnlyValidationError("telegram-token-file-missing")
    token = path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 512 or any(char.isspace() for char in token):
        raise TelegramReadOnlyValidationError("telegram-token-invalid")
    return token


def _redacted_telegram_error(exc: HTTPError) -> TelegramReadOnlyValidationError:
    code: str | int = exc.code
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        if isinstance(payload, dict) and payload.get("error_code") is not None:
            code = payload["error_code"]
    except (ValueError, OSError):
        code = exc.code
    return TelegramReadOnlyValidationError(f"telegram-api-error-{code}")


def _probe_bot_get_me(
    token_file: str,
    *,
    opener: Callable[..., BinaryIO] = urlopen,
) -> bool:
    token = _read_token(token_file)
    url = f"https://api.telegram.org/bot{token}/getMe"
    request = Request(url, method="GET")
    try:
        response = opener(request, timeout=20)
        payload = json.load(response)
    except HTTPError as exc:
        raise _redacted_telegram_error(exc) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise TelegramReadOnlyValidationError(
            f"telegram-api-read-failed-{type(exc).__name__.lower()}"
        ) from None
    finally:
        token = ""
        url = ""

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise TelegramReadOnlyValidationError("telegram-api-response-invalid")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("is_bot") is not True:
        raise TelegramReadOnlyValidationError("telegram-api-result-not-bot")
    return True


def probe_telegram_bots_read_only(
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, Any]:
    """Validate the two owner-installed Telegram bot credentials via getMe only."""

    admin_file = _safe_token_file(ADMIN_TOKEN_FILE_ENV)
    user_file = _safe_token_file(USER_TOKEN_FILE_ENV)
    admin_verified = _probe_bot_get_me(admin_file, opener=opener)
    user_verified = _probe_bot_get_me(user_file, opener=opener)
    verified_count = int(admin_verified) + int(user_verified)
    if verified_count != 2:
        raise TelegramReadOnlyValidationError("telegram-bot-verification-incomplete")

    return {
        "provider": TELEGRAM_PROVIDER,
        "capability": TELEGRAM_CAPABILITY,
        "scope": TELEGRAM_SCOPE,
        "validation_mode": TELEGRAM_VALIDATION_MODE,
        "credential_refs": [ADMIN_CREDENTIAL_REF, USER_CREDENTIAL_REF],
        "bot_credentials_count": 2,
        "verified_bot_count": verified_count,
        "provider_call_allowed": True,
        "mutation_allowed": False,
        "send_allowed": False,
        "spend_allowed": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def record_telegram_read_only_verified(evidence: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(GrowthSocialProviderCapability).where(
                GrowthSocialProviderCapability.provider == TELEGRAM_PROVIDER,
                GrowthSocialProviderCapability.capability == TELEGRAM_CAPABILITY,
            )
        )
        if row is None:
            row = GrowthSocialProviderCapability(
                provider=TELEGRAM_PROVIDER,
                capability=TELEGRAM_CAPABILITY,
                verification_state="unverified",
                mutation_class="read",
                evidence={},
            )
            session.add(row)

        stored = dict(row.evidence or {})
        stored["gs09_telegram_read_only"] = {
            key: value for key, value in evidence.items() if key != "credential_refs"
        }
        stored["credential_refs"] = [ADMIN_CREDENTIAL_REF, USER_CREDENTIAL_REF]
        stored["raw_secret_persisted"] = False
        row.evidence = stored
        row.verification_state = "read_only_verified"
        row.mutation_class = "read"
        row.verified_at = datetime.now(timezone.utc)
        row.version = int(row.version or 0) + 1
        await session.commit()


async def validate_and_record() -> dict[str, Any]:
    evidence = probe_telegram_bots_read_only()
    await record_telegram_read_only_verified(evidence)
    return evidence


def _print_safe_evidence(evidence: dict[str, Any]) -> None:
    print("AIOS_TELEGRAM_READ_ONLY_VALIDATION_OK")
    print("provider=telegram")
    print("capability=account.read")
    print("scope=owner_bots")
    print("verification_state=read_only_verified")
    print(f"bot_credentials_count={evidence['bot_credentials_count']}")
    print(f"verified_bot_count={evidence['verified_bot_count']}")
    print("provider_call_allowed=true")
    print("mutation_allowed=false")
    print("send_allowed=false")
    print("spend_allowed=false")
    print("raw_secret_persisted=false")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-bots-read-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_bots_read_only:
        raise SystemExit("use --validate-bots-read-only")
    evidence = asyncio.run(validate_and_record())
    _print_safe_evidence(evidence)


if __name__ == "__main__":
    main()
