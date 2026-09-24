# 36H — Room-bound participant administration correction

FR-06C5D9B4D fixes a real disposable LiveKit 1.13.5 401 failure in participant removal by binding participant administration and inventory grants to the exact room, with only the roomAdmin permission. Signed-token regressions and a real PostgreSQL/LiveKit control-plane canary cover the correction, including rejection of a different room grant and preservation of valid credential ownership after leave.

See `docs/project/receipts/FR-06C5D9B4D-livekit-room-admin-scope.md`. Current execution and merge/deployment acceptance remain in `/opt/AIOS/docs/project/PROJECT-REPORT.md`. No audio/video media session, Egress recording, production TURN drain, production deployment, or full-host closure is claimed by this source receipt.
