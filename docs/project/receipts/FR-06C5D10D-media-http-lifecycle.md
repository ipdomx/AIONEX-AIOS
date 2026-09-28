# FR-06C5D10D — Media file-bearing HTTP lifetime admission

Base source: accepted PR771 main `564d5754c7a6c5780d77ff09cab327e1ba413364`.
D10B worker-cycle and D10C queue-publication work remain separately owned branches;
this change does not alter their worker/enqueue implementations. FR-07 remains
completed and deployed. This source receipt is not a deployment certificate.

## Gap and boundary

Claim and queue guards cannot by themselves protect a file write preceding queue
publication, nor cleanup after a business transaction commits or rolls back.
FastAPI multipart parsing may spool an upload before the endpoint body starts.
A FileResponse may still access its file after the endpoint returned a Response.
The song artifact GET also creates its root and purges stale files, so treating
it as a harmless status read was incorrect.

The unchanged-source baseline reproduced44 failures among46 actual ASGI and
PostgreSQL cases. The two open/ordinary-routing controls passed. The first patch
left four failures because a 3D artifact-link handler was misnamed in the explicit
registry; the actual handler name was corrected and the failing run retained.
No runtime authorization or scanner/test rule was weakened.

## Implemented scope

`MediaFileRoute.handle` holds an independent PostgreSQL shared Studio-maintenance
lock over the whole selected ASGI request. This begins before multipart parsing,
request-body consumption and endpoint dependencies, and ends after response-body
transmission, background tasks and rollback cleanup return. An inner business
session's commit/rollback cannot release this separate lock-only transaction.
The guard does not seed or update authority and introduces no migration.

Exactly eleven entrypoints in three routers are covered: song artifact upload,
download and deletion; identity execution upload, provider-input retrieval and
output download; 3D create, clarify, cancel, local artifact download and artifact
link creation. Status-only routes, unknown URLs and unsupported HTTP methods
retain their original behavior. The existing endpoint auth, subject-consent,
rights, billing, hash/write-once and tenant rules execute unchanged when admission
is open. Closed/missing/malformed/insufficient authority returns generic HTTP503
without consuming the body or disclosing an artifact's existence.

Cancellation before admission cancels the lock waiter without executing the
handler. After admission, outer cancellation is deferred until the one existing
ASGI task finishes; repeated cancellation never spawns or retries another handler.
This keeps the maintenance lock held while `to_thread` storage work or response
cleanup remains active. Cancellation is reported to the caller afterwards, even
when the protected cleanup concurrently raises. No detached background work is
created by this protocol.

## Executed acceptance

The final focused suite passed62 cases using actual isolated PostgreSQL and
FastAPI/Starlette ASGI handling. It includes the real song WAV upload, checksum,
write-once duplicate, token action boundary, file response and deletion path.
Closed requests preserve an existing stale artifact byte-for-byte and do not
consume multi-megabyte multipart bodies. All eleven real routes reject closed,
missing, malformed and insufficient-version authority before their dependencies.

Actual PostgreSQL lock waits establish that a closer waits through upload-body
streaming, file-response transmission, business commit/rollback, background work
and cleanup. A real blocking storage thread writes an exclusively owned file;
repeated cancellation cannot let close pass before that thread finishes, including
its failure path. A request cancelled while waiting for admission never executes
its body. Programming exceptions remain exceptions, not successful admission.

The preliminary combined media regression passed374 cases, including the first55
focused tests. A later final regression result, when present, is recorded in the
canonical runtime evidence rather than inferred from this earlier count. These
overlapping suites must not be added as disjoint test coverage.

No real provider, paid inference, production credential or customer data was used.
All test databases, networks and files were exclusively owned disposable resources;
cleanup absence was verified. Executed and failed results are retained under:
`docs/project/runtime/fr06d10d-media-http-lifecycle-20260928/`.

## Limits retained

This is a request-lifetime fence, not a full-host drain proof. A stuck admitted
handler can delay maintenance; a close timeout fails rather than forcibly dropping
its protection. Process death, an independently cancelled inner task, or a lost
DB connection during a filesystem operation require separate reconciliation and
are not represented as safe crash drainage. Remote computation already dispatched
is not recalled. Direct internal Python invocations of endpoint functions do not
traverse an ASGI route and must use their own guarded operator contract.

Other routers, workers, administrative producers, provider evidence, deployment
serialization and encrypted host-state cutover remain independently required.
The blocked Replicate inventory was not retried and its state remains UNKNOWN;
no historical needs_review record was altered. No production images, services,
Cloudflare configuration, DNS, tunnel, key or schema changed in this laboratory.
