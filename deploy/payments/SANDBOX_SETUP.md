# Payments Sandbox Setup

1. Copy `.env.sandbox.example` to `.env.sandbox`.
2. Add sandbox credentials for Stripe, PayPal, and Paddle.
3. Register `ai.vip-e.net` for Apple Pay domain verification in the payment provider dashboard.
4. Configure webhook endpoints to the AIOS payments API.
5. Run `bash deploy/payments/validate-sandbox-env.sh`.
6. Keep production credentials disabled until all sandbox tests pass.

Local providers may remain empty until their merchant sandbox accounts are available. Bank transfer fields are optional during automated sandbox testing.
