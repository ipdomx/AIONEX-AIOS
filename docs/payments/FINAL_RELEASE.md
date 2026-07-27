# AIONEX AIOS Payments & Billing Final Release

Batches 1 through 10 complete the payments and billing foundation.

## Included

- Core provider contracts and registry
- Plans, trials, subscriptions, upgrades, cancellations
- Stripe with Apple Pay and Google Pay enablement
- PayPal and Paddle provider contracts
- Wallet, credits, and pay-as-you-go usage charging
- Invoices, taxes, coupons, refunds, and multi-currency money handling
- Local provider framework for Paymob, Fawry, STC Pay, Mada, and bank transfer
- Owner finance reporting service
- Final release validation gate and webhook signature verification

## Required before live deployment

1. Configure sandbox credentials for each enabled provider.
2. Register webhook endpoints and secrets.
3. Verify Apple Pay domain association through the selected payment processor.
4. Run the complete payment test suite and repository CI.
5. Execute sandbox checkout, subscription, refund, invoice, and webhook flows.
6. Enable production credentials only after sandbox sign-off.

No real payment secrets belong in the repository.
