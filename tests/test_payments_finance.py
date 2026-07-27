from decimal import Decimal

import pytest

from aios.payments.finance import Coupon, Invoice, InvoiceLine, InvoiceStatus, Money, TaxRate
from aios.payments.local_providers import (
    BankTransferProvider,
    ConfiguredLocalProvider,
    LocalCheckoutRequest,
    LocalProviderRegistry,
)


def checkout_request() -> LocalCheckoutRequest:
    return LocalCheckoutRequest(
        customer_id="customer-1",
        amount_minor=1250,
        currency="eur",
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        metadata={"project_id": "project-1"},
    )


def test_invoice_applies_coupon_and_exclusive_tax() -> None:
    invoice = Invoice(
        customer_id="customer-1",
        lines=[
            InvoiceLine(
                description="AIOS Pro",
                quantity=Decimal("1"),
                unit_price=Money(Decimal("100"), "EUR"),
                tax_rate=TaxRate("VAT20", Decimal("20")),
            )
        ],
        coupon=Coupon("SAVE10", percent_off=Decimal("10")),
    )

    assert invoice.subtotal == Money(Decimal("100"), "EUR")
    assert invoice.discount == Money(Decimal("10"), "EUR")
    assert invoice.tax == Money(Decimal("18"), "EUR")
    assert invoice.total == Money(Decimal("108"), "EUR")


def test_invoice_lifecycle() -> None:
    invoice = Invoice(
        customer_id="customer-1",
        lines=[InvoiceLine("Credits", Decimal("1"), Money(Decimal("25"), "EUR"))],
    )

    invoice.open()
    invoice.mark_paid()
    invoice.refund()

    assert invoice.status is InvoiceStatus.REFUNDED


def test_coupon_currency_must_match_invoice() -> None:
    invoice = Invoice(
        customer_id="customer-1",
        lines=[InvoiceLine("Credits", Decimal("1"), Money(Decimal("25"), "EUR"))],
        coupon=Coupon("USD5", amount_off=Money(Decimal("5"), "USD")),
    )

    with pytest.raises(ValueError, match="coupon currency mismatch"):
        _ = invoice.total


def test_local_provider_registry_and_checkout() -> None:
    registry = LocalProviderRegistry()
    provider = ConfiguredLocalProvider(
        name="paymob",
        api_key="test-key",
        webhook_secret="test-signature",
        checkout_base_url="https://pay.example.test/checkout",
    )
    registry.register(provider)

    result = registry.get("PAYMOB").create_checkout(checkout_request())

    assert result.provider == "paymob"
    assert result.status == "pending"
    assert result.redirect_url is not None
    assert registry.names() == ("paymob",)
    assert provider.verify_webhook(b"payload", "test-signature") is True


def test_bank_transfer_returns_payment_instructions() -> None:
    provider = BankTransferProvider(
        bank_name="AIONEX Bank",
        account_name="AIONEX AIOS",
        iban="CY00000000000000000000000000",
        swift="AIONCY00",
    )

    result = provider.create_checkout(checkout_request())

    assert result.status == "awaiting_transfer"
    assert result.instructions is not None
    assert result.instructions["currency"] == "EUR"
    assert result.instructions["reference"].startswith("BT-")


def test_duplicate_local_provider_is_rejected() -> None:
    registry = LocalProviderRegistry()
    provider = ConfiguredLocalProvider("fawry", "key", "secret", "https://fawry.test")
    registry.register(provider)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider)
