# FR-06C5D9B4D — Real LiveKit room-scoped administration correction

Base source: PR765 merge `22e94dc8afe892d5f80a0b71f55bac387ce571c1` (same tree as its tested head `0cd87a18`). This is a source correction and isolated-provider acceptance, not Production rollout or full-host drain. Current operational authority remains `/opt/AIOS/docs/project/PROJECT-REPORT.md` and the append-only runtime journal.

## Independently reproduced provider failure

The pinned LiveKit image `sha256:d0d1cfdbe95617647bbe91630454526c2cdd88cec83f41114b3495b444918b9a` accepted room listing and creation, but rejected both `ListParticipants` and `RemoveParticipant` with HTTP 401 when the existing global grant omitted `video.room`. A positive protocol control using `roomAdmin` with the exact requested room succeeded; using another room was rejected. Eight unit/JWT-boundary regression cases failed against the unchanged source, then passed with this correction.

## Minimal correction

Both participant operations now issue only `roomAdmin: true` and the exact requested room. They no longer carry unrelated room-create, list, or recording permissions. Global room deletion remains unchanged. No authorization failure is swallowed, no error is reclassified as empty inventory, and no missing/malformed inventory entry is relaxed. Durable ownership, operation/generation revalidation, cancellation, expiry, and no-replay behavior remain unchanged.

## Real isolated acceptance

The actual control-plane test used real PostgreSQL migrated to 0064, Redis, and the pinned LiveKit server on a private internal Docker network with synthetic credentials. The application collector was exercised under a real closed maintenance authority, without replacing its transport. Empty responses contained explicit `rooms`/`participants` arrays, so no protobuf-default exception was necessary.

The corrected collector observed zero rooms, then one independently created test room. A real synthetic WebSocket signaling participant appeared with count one and prevented the connected-presence bound. The application's `RemoveParticipant` succeeded, the signaling connection closed, and the participant count returned to zero while the room still existed. Explicit deletion of that owned lab room then returned the room count to zero. A wrong-room administrator token remained rejected; a nonexistent participant produced logical HTTP404 instead of the prior authentication failure.

No microphone, camera, audio/video tracks, customer records, production credentials, or production provider calls were used. The signaling test is not an end-to-end media quality or load certification. All specifically named lab containers and networks were removed and their absence checked.

Before/after logs, wire-shape summaries, signed-token tests, source hashes, and cleanup evidence are retained under `docs/project/runtime/d9b4-rollout-preflight-20260924/`, especially `real-livekit-baseline-contract`, `real-livekit-corrected-contract`, and `real-livekit-signaling-participant`.

## Release boundary

The preceding candidate image must not be treated as final for this corrected path. Rebuild/rebind the accepted source after protected CI; retain a schema-compatible, security-scanned rollback strategy. Production 0064, private TURN metrics activation, current credential closure, provider reconciliation, other host consumers, and full-host cutover remain independent operational gates. No whole-project release is asserted here.

Primary protocol references: https://docs.livekit.io/reference/other/roomservice-api/ and https://docs.livekit.io/frontends/reference/tokens-grants/ (the `room` field is required with room administration).
