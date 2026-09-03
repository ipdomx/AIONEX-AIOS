from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/validate-payments-env.sh"


def _run(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / "payments.env"
    env_file.write_text(text, encoding="utf-8")
    return subprocess.run(
        ["bash", str(VALIDATOR), str(env_file)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_current_sparse_stripe_contract_is_valid(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "\n".join(
            (
                "PAYMENTS_ENVIRONMENT=live",
                "STRIPE_SECRET_KEY=sk_live_example",
                "STRIPE_WEBHOOK_SECRET=whsec_example",
            )
        ),
    )
    assert result.returncode == 0, result.stderr
    assert "current AIOS payment contract" in result.stdout


def test_live_stripe_test_key_is_rejected(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "\n".join(
            (
                "PAYMENTS_ENVIRONMENT=live",
                "STRIPE_SECRET_KEY=sk_test_example",
                "STRIPE_WEBHOOK_SECRET=whsec_example",
            )
        ),
    )
    assert result.returncode != 0
    assert "must not use a Stripe test key" in result.stderr


def test_partial_provider_credentials_are_rejected(tmp_path: Path) -> None:
    result = _run(tmp_path, "PAYPAL_CLIENT_ID=client-only\n")
    assert result.returncode != 0
    assert "PayPal configuration is incomplete" in result.stderr


def test_google_pay_requires_stripe_when_explicitly_enabled(tmp_path: Path) -> None:
    result = _run(tmp_path, "GOOGLE_PAY_ENABLED=true\n")
    assert result.returncode != 0
    assert "require the configured Stripe adapter" in result.stderr


def test_direct_apple_pay_stays_fail_closed(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "\n".join(
            (
                "STRIPE_SECRET_KEY=sk_test_example",
                "STRIPE_WEBHOOK_SECRET=whsec_example",
                "APPLE_PAY_ENABLED=true",
            )
        ),
    )
    assert result.returncode != 0
    assert "Direct Apple Pay is an external activation boundary" in result.stderr
    assert "Merchant ID" in result.stderr


def test_checked_in_payment_example_matches_validator_contract() -> None:
    result = subprocess.run(
        ["bash", str(VALIDATOR), str(ROOT / "deploy/production/.env.payments.example")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
