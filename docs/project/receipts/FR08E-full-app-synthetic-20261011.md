# FR08E full-application synthetic subgate — 2026-10-11

Status: **PASS for this bounded subgate only**. FR-08 remains **IN_PROGRESS** and the actual 5,000-user workload remains **NOT_RUN**.

## Immutable scope

- Host: `nc-ph-4354`
- Native application source: `f2527cf3815d21353916697e61a3409d2a9c62b3`
- Protected main observed by the run: `ca9aaaa3ffcf1002c73b826c46bce598d029811f`
- Isolated fresh PostgreSQL 16 and Redis
- Full current FastAPI router/lifespan boot from an exact git-archive projection
- Synthetic identity only; no customer/R2 data, production secrets, external providers, paid requests, deployment, or production mutation

## Result

All **20/20** checks passed:

- original Alembic migrations reached head `20260920_0064`;
- the current application router tree loaded with 64 API router nodes;
- `/health` and `/ready` returned HTTP 200;
- unauthenticated project access returned HTTP 401;
- native login returned HTTP 200 and issued access/refresh tokens;
- authenticated project and conversation creation returned HTTP 201;
- project/conversation listing and PostgreSQL persistence passed;
- unknown path remained HTTP 404;
- no-store and security headers passed, server identity was suppressed;
- application lifespan shutdown exited 0.

The source projection contained 1,215 tracked entries: 733 backend entries and 482 `src/aios` entries. The functional journey took 436.1 ms; this is not a load/SLO acceptance result.

## Isolation and cleanup

The lab used network mode `none`, no host ports, read-only root filesystems, no privileged containers, fresh databases, and no outbound provider traffic. All temporary containers, databases, source projections, and synthetic state were removed. Production remained 36 running / 35 healthy / 0 unhealthy with container identities and restart counters preserved. Lab free space after cleanup was 119.14 GiB.

## Boundaries

This subgate does **not** prove full FR08E acceptance, full customer R2 recovery, worker/media/inference acceptance, deployment, or actual 5,000-user capacity. FR09 workload admission remains closed until all independent FR08 acceptance requirements are complete.

## NEW evidence

- Checkpoint: `/var/lib/aionex-migration/r1-management-20261008/FR08E-FULL-APP-SYNTHETIC-20261011T225500Z/CONTINUATION-CHECKPOINT.json`
- Checkpoint status: `PASS`
- Proof SHA-256: `83d6d504b4c3765371e82ba9bf36b78ffa914288ff1180ca928608c505c651e6`
- Lab receipt SHA-256: `22e39286fd65feb62eae2d56847d398ad3f419083369131ce647de1480300dd7`
- Source manifest SHA-256: `25e7b6a97fabcad94a8a031bbb9e5d6009a3ed3c0d9f318838bf4eaae341361f`
- Canonical event: `fr08e-full-app-synthetic-subgate-20261011T230730Z`
