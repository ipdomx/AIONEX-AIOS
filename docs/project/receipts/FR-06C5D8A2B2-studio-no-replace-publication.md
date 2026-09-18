# FR-06C5D8A2B2 — Local no-replace Studio archive publication

Base: PR #726 merged as `7c331aa40470bd4882296b2ffc663ddd48f0fea5`.
This increment is source-only and deliberately does not deploy the incomplete
Studio maintenance family or close FR-06.

## Implementation and boundaries

`production_studio.store_artifact` retains its Path-returning interface and now
uses `studio_artifact_publication.publish_studio_archive`. Payload length,
checksum, maximum size, revision number and path components are validated before
payload storage. Directories are opened relative to pinned descriptors with
O_DIRECTORY/O_NOFOLLOW; configured root resolution does not follow symlinks.
The configured root and business directories must belong to the current writer
and must not be group/world writable. Existing directory modes are not changed.

The writer creates one exclusive randomly named staging file, writes all bytes,
flushes it, verifies the readback checksum, and uses a same-directory hard link
to create the final name. There is no exists-then-replace operation or fallback.
Existing regular files, identical content, symlinks, dangling links, directories,
FIFOs and hard links remain collisions, never idempotent success.

Only the identity-checked staging name can be removed by this module. Directory
sync, identity changes and cleanup errors propagate; the final name is never
removed on an ambiguous result. Directory descriptors pin writes/cleanup to the
original directories. A crash between link and unlink can leave two names; that
is unresolved evidence, not a reason to replay the job or declare host drain.
An unsupported hard-link/filesystem operation fails closed.

This bounded change does NOT add durable resource registration, settle Studio
jobs, change cancellation/retry authority, update the worker's later path-based
cleanup, reconcile historical work or protect subsequent path-based readers.
Same-UID/root malicious namespace races after checks remain outside this local
publication contract; production containment and ownership-bound cleanup remain
required. Existing completed LiveKit recording finalization is not changed.
The temporary hard-link interval requires quiescent backup/drain acceptance;
no deployment should infer that those broader prerequisites are complete.

## Observed acceptance and remaining gates

The initial isolated networkless run passed 77 new real-filesystem cases,
including 16 concurrent writers with one complete winner, no-replace collisions,
short writes, injected write/fsync/link/cleanup failures, directory replacement,
symlink rejection, retained ambiguous final output and descriptor closure.
The established archive builder/store/verify interface was exercised on an
actual generated ZIP, without external provider calls.

An initial read-only-source regression run reached 282 passes and failed at a
database-settings shell-harness test. That attempt is retained, not counted as
full acceptance. Final regression/source-copy outcomes, source hashes, main/PR
checks, isolated QA cleanup and any limitations are recorded in the canonical
runtime directory `docs/project/runtime/fr06c5d8a2b2-20260918/`.

The existing runner images lacked local Ruff/mypy/pip. Attempts to bootstrap
quality tools in disposable containers did not succeed and do not establish
static acceptance. The exact-head GitHub backend Ruff/mypy jobs must pass before
merge. No quality threshold or test was weakened.

## Primary implementation references

- Python 3.11 os interfaces: descriptor-relative link/open/stat/unlink and fsync:
  https://docs.python.org/3.11/library/os.html
- Linux link(2): no existing new-path replacement, hard-link and error semantics:
  https://man7.org/linux/man-pages/man2/link.2.html

No production database migration, container recreation, vault transfer,
Cloudflare configuration change, provider replay or forced merge is performed
by this source increment. Main acceptance of #726 is separate from this PR.
