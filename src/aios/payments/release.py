from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class ReleaseCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReleaseReport:
    checks: tuple[ReleaseCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checks": [
                {"name": check.name, "passed": check.passed, "detail": check.detail}
                for check in self.checks
            ],
        }


class PaymentReleaseGate:
    """Final validation gate for the payments and billing platform."""

    def __init__(self, checks: Iterable[Callable[[], ReleaseCheck]]) -> None:
        self._checks = tuple(checks)

    def run(self) -> ReleaseReport:
        return ReleaseReport(tuple(check() for check in self._checks))


def check_provider_registry(registry: object) -> ReleaseCheck:
    providers = list(getattr(registry, "providers", lambda: [])())
    names = {getattr(provider, "name", provider.__class__.__name__).lower() for provider in providers}
    expected = {"stripe", "paypal", "paddle"}
    missing = sorted(expected - names)
    return ReleaseCheck(
        name="provider_registry",
        passed=not missing,
        detail="all core providers registered" if not missing else f"missing providers: {', '.join(missing)}",
    )


def check_payment_methods(registry: object) -> ReleaseCheck:
    providers = list(getattr(registry, "providers", lambda: [])())
    text = " ".join(
        str(getattr(provider, "payment_methods", "")) for provider in providers
    ).lower()
    google_pay_ready = "google" in text
    return ReleaseCheck(
        name="wallet_payment_methods",
        passed=google_pay_ready,
        detail=(
            "Google Pay is enabled through the Stripe adapter; direct Apple Pay "
            "remains a separate external activation boundary"
            if google_pay_ready
            else "missing wallet method: google"
        ),
    )


def verify_signed_webhook(payload: bytes, signature: str, secret: str) -> bool:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def serialize_release_report(report: ReleaseReport) -> str:
    return json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
