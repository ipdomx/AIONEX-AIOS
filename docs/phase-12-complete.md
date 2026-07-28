# Phase 12 — Meetings, Access, and Monetization

Phase 12 batches 4 through 6 complete the role-session platform with:

- Staff availability and conflict-safe booking
- Owner confirmation, cancellation, and completion controls
- Session entitlements and minute consumption
- Paid-session settlement, platform fees, staff allocation, refunds, and voids
- Owner and user scope enforcement
- Lifecycle and accounting tests

## Completion criteria

1. CodeQL passes.
2. Final Validation passes.
3. Bookings require matching active staff availability.
4. Overlapping active bookings are rejected.
5. Only the owner can confirm or complete a booking.
6. Entitlements reject expired, mismatched, or insufficient balances.
7. Settlement splits equal the gross amount.
8. Refunds only follow captured payments.

After this pull request is merged, Phase 12 is complete and the project can proceed to Phase 13: API Gateway and Final Web Dashboard.
