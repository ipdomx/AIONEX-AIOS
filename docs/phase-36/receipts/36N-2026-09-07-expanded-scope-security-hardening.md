# Phase 36N — Expanded-Scope Security Hardening — 2026-09-07

## Owner scope expansion

The Owner expanded the completion contract on 2026-09-07. AWS credential authority, AWS Bedrock and XR/device validation are deferred to the final tail only. All other previously post-XR or optional/internal completion work returns to the active completion program, including release engineering, source-debt cleanup, Growth/Social readiness, payment/mobile internals, observability, off-host/HA prerequisites, and every other internally satisfiable item.

External facts are still not fabricated. Voice/music rights, platform signing, merchant/social account authority, physical-device/chain authority, second-host/off-site infrastructure and similar boundaries may only transition when real authority/evidence exists; their internal fail-closed controls remain mandatory.

## Security finding discovered during expanded-scope verification

A bounded non-secret production configuration probe found that the root-owned `web-dashboard/.env.production` file is correctly Git-ignored, untracked, mode `0600`, UID/GID `0:0`. However, the current running application containers still receive the historical bootstrap `SECRET_KEY`, and the bundled PostgreSQL environment still carries the historical bootstrap database password. The live application therefore requires secret rotation before the expanded completion program can be certified.

No secret value is included in this receipt.

## Recovery anchor before mutation

A new durable platform backup was created through the production Backup Worker before any credential mutation:

- Backup ID: `b152a5f4-3b05-4901-aa07-a747e6a67df7`.
- Status: `completed`.
- Size: `20,484,783` bytes.
- SHA-256: `cee49c3594281902de41f6925b8d9015d0171da1a0776b67b15947af263f3b40`.

A matching restore validation was then queued and completed:

- DR run ID: `55c71b3e-4669-4e9d-a03e-f4c266ee6290`.
- Status: `completed`.
- `validated=true`.
- 3D snapshot validation: `true`.
- Production database was not replaced; validation used the governed scratch/dry-run path.

## Source hardening candidate

Branch: `completion-expanded-scope-20260907`.

The candidate adds file-backed runtime secret support instead of replacing one plaintext environment secret with another:

- `SECRET_KEY_FILE` can override the legacy environment value.
- `POSTGRES_PASSWORD_FILE` can override the legacy environment/URL password and rebuild the internal SQLAlchemy URL from the private file value.
- Production rejects the historical bootstrap application secret when no secure file override exists.
- Runtime secret files must be absolute, regular, non-symlink files with no group/other permissions and exactly one non-empty line.
- The PostgreSQL credential reconciler independently supports the private password file with the same fail-closed regular-file/permissions rules.
- Both production Compose definitions provide read-only `/workspace` access to the PostgreSQL reconciler and optional `POSTGRES_INIT_PASSWORD_FILE` support for the bundled PostgreSQL container.
- The production Compose contract no longer requires a non-empty `POSTGRES_PASSWORD` environment value when the private password-file path is used; CI/test deployments may still use the legacy environment value when no file is configured.
- No secret is copied into a Docker image or Git source.

Host runtime secret files have been prepared under the existing Git-ignored secrets tree but are not yet activated. File metadata only:

- runtime directory: mode `0711`, root-owned, no directory listing for non-root users;
- application secret file: mode `0400`, UID/GID `1000:1000`;
- application PostgreSQL password file: mode `0400`, UID/GID `1000:1000`;
- PostgreSQL initialization copy: mode `0400`, UID/GID `70:70`;
- tracked secret files: `0`.

## Local validation

Focused existing + new database/credential regression inside the backend test image:

- `61 passed, 0 failed`.

New regressions cover:

- file-backed application and PostgreSQL secrets overriding stale environment values;
- production rejection of the bootstrap application secret;
- rejection of group/other-readable secret files;
- rejection of symlink secret files;
- PostgreSQL reconciler preference for the private password file;
- production Compose password-file/workspace contract.

Local test images do not contain Ruff/Mypy. Static quality remains a required protected GitHub CI gate; no static gate is bypassed.

## Production boundary

No running Production container has been recreated from this candidate and no PostgreSQL role password has been changed yet. The current Production source/runtime remains the previously certified protected release until this candidate passes protected CI and merges.

After merge, the activation order is fail-closed:

1. add only secret-file path variables to the root-owned Git-ignored production environment;
2. run the PostgreSQL credential reconciler against the existing database through the trusted Unix socket;
3. verify password-authenticated TCP using the new private file value;
4. recreate all DB/JWT application clients, preserving four Project Worker replicas;
5. recreate PostgreSQL only after all application clients are running on the new credential so its runtime metadata also reflects file-backed initialization;
6. prove the resolved runtime `settings.SECRET_KEY` is non-bootstrap and sufficiently strong without printing it;
7. prove the resolved PostgreSQL credential is non-bootstrap without printing it;
8. verify all service health, queues, recent logs, backup/DR and Owner finalization remain green.

No branch-protection bypass and no secret readback are permitted.
