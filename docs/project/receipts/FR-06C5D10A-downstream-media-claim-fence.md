# FR-06C5D10A — Supplemental downstream media claim and reaper admission

Base: accepted and deployed `0151b1aa2dcc4dd7c743ec6ffc27f55e32b242fa`
(PR770). FR07 remains complete in the canonical execution journal. This increment
addresses the first remaining FR06 worker-coverage requirement; it does not
repeat the completed conversation deployment or the blocked provider inventory.

## Reproduced failure and implemented behavior

On unchanged application source, 21 of 32 private PostgreSQL cases failed.
Eleven real claim paths reached their work tables while the maintenance record
was explicitly closed, and six lease-reaper paths did the same. Two actual
identity-media fixture rows were claimed for submit/poll despite closed
maintenance. Two expired local-render fixtures and their graphs were rewritten
by reapers during closure. These were synthetic records in a separate database,
not a claim that production customer work was damaged.

The eleven consumers now take the existing Studio-request shared authority lock
before touching their queue inside the SAME database transaction. The six
reapers take that lock in their own mutation transaction as well. The named
consumers are design image, stock speech, transcription, dubbing, music, open
song, video, identity media, 3D generation, FFmpeg rendering and Sharp derivatives.
Closed, missing, malformed or unsupported authority returns no claimed work and
performs no lease transition, automatic state repair, seeding or queue access.
Unknown consumer names and non-database programming errors are not swallowed.

This is a conservative supplemental use of the already deployed Studio-request
fence. It does not change the versioned authority payload or certify a broader
schema coverage declaration. Source and process/image attestation are separate;
old running images are not retroactively protected by this source receipt.

## Executed PostgreSQL acceptance

The original 32 cases passed after correction without changing those test cases.
The expanded suite passed 61/61 cases with no skips or errors. This includes
missing authority for every consumer, malformed and too-old scope records,
unknown schemas, read-only transaction rejection, unflushed caller mutations,
cached ORM authority, positive open claims and existing open reaper behavior.

Concurrency tests used distinct PostgreSQL connections and observed actual
`pg_blocking_pids`/lock waits. Closure waited for a successfully admitted claim's
caller commit or rollback. Conversely, a claimant that waited behind an
exclusive closure lock was rejected after that closure committed. A failed or
rolled-back claim did not acquire durable usage or lease ownership.

The combined existing Phase36G audio/open-song/music, Phase36E image, Phase36F
video and new fence regression suite passed 274/274 cases without skips/errors.
Those 274 include the 61 new cases; the counts must not be added together.
Tests use existing images, private tmpfs PostgreSQL/Redis and a read-only source
mount. No provider client, paid request, external inventory, media generation,
production data, production schema or production service was changed.
Every disposable container/network was removed and its absence verified.

## Boundaries still required for FR06

This increment is a claim/reaper fence, NOT producer admission or provider drain.
Work claimed before closure may still run and remains an independent drain
blocker. Initial producer writes, explicit arm paths, provider input grants,
preflights and output publication are not certified by these changes. Existing
open-state retry/recovery semantics have not been changed or declared safe for
host cutover. A failed business status alone is not provider settlement proof.

The blocked Replicate account inventory remains UNKNOWN and was not retried.
No full-host evidence, migration, host-state bind, provider settlement, automatic
adoption or host restart is authorized by this receipt. Protected candidate CI,
post-merge CI and independently accepted selective runtime activation are still
required before claiming this code is deployed. The historical FR07 completion
is preserved, and the entire project is not marked released.

Runtime evidence directory:
`docs/project/runtime/fr06d10a-media-claim-fence-20260928/`

Full local quality acceptance: root source suite2212/2212; Ruff over app/tests;
Mypy over305 application source files. These are separate from the274 combined
backend regressions above. No lint rule, authentication guard or release gate
was disabled.
