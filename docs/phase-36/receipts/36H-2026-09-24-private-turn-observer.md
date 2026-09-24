# 36H — Private Coturn observer, isolated acceptance

Source-only independent work based on accepted main `9439a7f0520f38fb4c0ed6f966729f1bd3ccdc06`. Canonical execution status remains `/opt/AIOS/docs/project/PROJECT-REPORT.md` and its append-only runtime journal.

The exact-instance host reader now measures the pinned Coturn allocation gauge through the daemon's private loopback network namespace, with two-point container/process/socket-epoch checks and strict missing/duplicate/malformed metric rejection. Its output is aggregate-only and never authorizes migration, provider drain or full-host closure.

112 executable unit cases and real disposable UDP plus TCP allocation/expiry exercises are documented in `docs/project/receipts/FR-06C5D9B4B-private-turn-observer.md`. Missing allocation series remained UNKNOWN; positive counts were observed before explicit zero counts without restarting the daemon. No production setting, public listener, secret, admission state, deployment or migration was changed. PR762 acceptance and fresh authority/credential/fleet binding remain prerequisites to any independent production integration.
