from dataclasses import dataclass
from decimal import Decimal

from aios.payments.admin import FinanceAdminService
from aios.payments.release import PaymentReleaseGate, ReleaseCheck, serialize_release_report, verify_signed_webhook


@dataclass
class Item:
    amount: Decimal = Decimal("0")
    status: str = ""


class Source:
    def transactions(self):
        return [Item(Decimal("100"), "succeeded"), Item(Decimal("25"), "failed")]

    def subscriptions(self):
        return [Item(status="active"), Item(status="cancelled")]

    def invoices(self):
        return [Item(status="open"), Item(status="paid")]

    def refunds(self):
        return [Item(Decimal("20"), "succeeded")]


def test_finance_summary():
    summary = FinanceAdminService(Source()).summary()
    assert summary.gross_volume == Decimal("100")
    assert summary.refunded_volume == Decimal("20")
    assert summary.net_volume == Decimal("80")
    assert summary.successful_transactions == 1
    assert summary.failed_transactions == 1
    assert summary.active_subscriptions == 1
    assert summary.open_invoices == 1


def test_release_gate_and_serialization():
    report = PaymentReleaseGate(
        [
            lambda: ReleaseCheck("database", True, "ready"),
            lambda: ReleaseCheck("webhooks", True, "ready"),
        ]
    ).run()
    assert report.passed is True
    assert '"passed":true' in serialize_release_report(report)


def test_signed_webhook_validation():
    import hashlib
    import hmac

    payload = b'{"event":"payment.succeeded"}'
    secret = "secret"
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signed_webhook(payload, signature, secret)
    assert not verify_signed_webhook(payload, "invalid", secret)
