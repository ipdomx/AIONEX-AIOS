# Phase36 36H — Supplemental Telegram worker admission

Date: 2026-09-28. Related part: FR-06C5D11A. FR-07 remains completed.

Both Telegram worker loops now consult existing maintenance authority before
polling and reacquire an independent shared lock before command batches or bot
identity registration. The guard retains accepted action lifetimes across inner
transactions and outer cancellation. Denied batches do not advance durable or
in-memory offsets. Stop requests do not start another update in an admitted batch.

Baseline reproduced ten failures among twelve real worker-loop/PostgreSQL tests.
Expanded acceptance and existing authentication/security regressions are retained
under the canonical runtime directory. Telegram transport is explicitly fake in
these laboratories; no live bot messages or provider requests are sent.

See `docs/project/receipts/FR-06C5D11A-telegram-action-admission.md` for scope,
evidence, cancellation/offset behavior and remaining production/provider limits.
No versioned authority scope, production deployment or full-host closure is claimed.
