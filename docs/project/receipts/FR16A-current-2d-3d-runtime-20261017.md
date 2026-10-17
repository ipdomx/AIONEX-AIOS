# FR-16A — Current 2D/3D source and runtime inventory

Date: 2026-10-17 UTC. Scope: AIONEX AIOS on NEW `nc-ph-4354` only.

Status: **inventory and operating-document correction completed; FR-16 remains in progress**.

## Baseline and method

The reviewed protected-main source was
`43de0fee260750d6eba002d16ef59f70a35ccc24`, tree
`745b3414d6a9ffeed3e832be73494e8eaa328f0b`.
Ten selected source/document blobs were read from this immutable commit and
compared byte-for-byte with the intentional deployment checkout at
`/opt/AIOS`. All ten matched. The existing deployment checkout and its unrelated
overlays were preserved; this documentation change uses an isolated worktree.

Local queries in the existing backend imported the original provider-policy
module and returned only non-secret booleans and the already tracked quarantined
image digest. No provider request, job submission, paid generation, production
restart or configuration change was needed.

## Current inventory

| Area | Evidence and current observation | Remaining acceptance |
|---|---|---|
| 2D animation and games | `src/aios/three_d_web/two_d.py` matches the historical source SHA below. It emits local HTML/JavaScript and checksum manifests. The unchanged source schedules at most 240 animation frames or 300 game frames. The retained historical Chromium evidence exercises short clips and controls. | Full current FR-16B acceptance is open. The frame limits and short historical test must be considered when defining sustained interactive behavior; no new browser run or source repair is claimed. |
| Local Blender 3D expansion | `blender_candidate.py` implements the bounded offline PBR/material/animation/environment candidate. On NEW, neither the historical executable path `/opt/AIOS/.runtime/phase36i/blender-5.2.0/blender` nor `/usr/bin/blender` exists, and `/opt/AIOS/.runtime` is absent. | Restore or provision the verified renderer into the isolated encrypted workspace and perform fresh candidate acceptance. Absence at these paths is not proof that every container or archive lacks Blender. No renderer was downloaded or installed in this inventory. |
| TripoSR | Original deployed `provider_runtime_configured("triposr")` returned `true`; its source/model revisions remain pinned. The existing 3D worker is running and healthy. | Local configuration and worker health do not prove current external endpoint health, a fresh generated asset, PBR, or complete FR-16E recovery. |
| Hunyuan3D | Reviewed source and deployed module both return `HUNYUAN_RUNTIME_SECURITY_APPROVED=False`, with quarantined digest `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`. | FR-16D requires a rebuilt image with fresh security and functional evidence before activation. Historical Phase 34C PBR success cannot clear the quarantine. |
| 3D storage and delivery | `three_d_asset_backup.py` and `three_d_project_delivery.py` match the reviewed source. The general latest-generation restore has separate evidence for 251 files. | A total across all asset types does not establish recovery of a nonempty 3D asset. The 3D-specific recovery and authenticated delivery chain remain open. |

## Source identity

| File | SHA-256 |
|---|---|
| `src/aios/three_d_web/two_d.py` | `f992d00c15ca37d0a8156891be2e47b145a0d5e90494f424214ffe35af82241b` |
| `src/aios/three_d_web/expansion.py` | `c8d2432282b242311ee2c373e290f6d565c19c058f92de08cc0cf5c97c6fd02a` |
| `src/aios/three_d_web/blender_candidate.py` | `7f4fc35687e6f5d5183dbce0a9eed322fd095bbe0860243146740ef96f3823f4` |
| `web-dashboard/backend/app/services/three_d_provider_policy.py` | `1594f2a8cd1faeecf015a990c230a1ab10a2b20216a38a72021486bb74cdff47` |
| `web-dashboard/backend/app/services/three_d_asset_backup.py` | `daf1795b8327bfb369a39ac27a5480ced94cdb5db437a7e2132871928185f498` |
| `web-dashboard/backend/app/services/three_d_project_delivery.py` | `b35179a35a8973eb6433dd5cd4dab4f617d4fd095d08f93fdb7a1d34f0373c0e` |
| `infra/runpod/triposr/Dockerfile` | `cbdfc811406666f7584664225ae48675a88ad450050624941abdc43bca73a15b` |
| `infra/runpod/hunyuan3d/Dockerfile` | `f2b59b1f36a456a9aa9654420f0bd8e22630b0b87f6465b57a6617ef2fd3d1ab` |

TripoSR source remains pinned to
`107cefdc244c39106fa830359024f6a2f1c78871`, and its model revision to
`5b521936b01fbe1890f6f9baed0254ab6351c04a`.
These identifiers attest source selection, not a fresh image vulnerability scan.

## Correction made

The Hunyuan [README](../../../infra/runpod/hunyuan3d/README.md) and
[endpoint record](../../../infra/runpod/hunyuan3d/PRODUCTION_ENDPOINT.md)
previously called the quarantined v11 digest a known-good production image and
presented its recorded settings without the current security status. Both now
lead with the actual quarantine, distinguish recorded settings from live
control-plane evidence, and retain the original PBR output hashes and sizes as
historical evidence.

No application source, dependency, test assertion, quarantine constant or image
was changed.

## Production and continuation

The live Compose project contained **36 running containers, 35 healthy
healthchecks, zero bad states and zero restart counters**. All **23 worker
containers** were healthy. The one container without a healthcheck was the
running Cloudflare tunnel.

The canonical project review covered 26 release batches and 62 capabilities.
`project_hub.py validate` returned `PROJECT_HUB_VALIDATION_PASS`.
At the reviewed continuation point, NS12 had 21 clean natural hourly samples
through 09:00 UTC; its 72-hour acceptance remained open. The latest-generation
restore evidence and the already accepted public Portal result were retained.

FR-06 cold-host/key-custody acceptance, full authenticated FR-08E recovery and
same-generation worker/media resume, actual 5,000-user mixed load for 15 minutes,
and final release remain open. This FR-16A increment does not change their
acceptance status.

## Next FR-16 work

1. Resolve the NEW-host renderer path from a verified artifact in an isolated
   encrypted workspace, without replacing a system binary or activating Hunyuan.
2. Define and verify current 2D interactive behavior beyond the short historical
   clip before claiming full FR-16B acceptance.
3. Complete 3D asset generation, authenticated delivery and nonempty recovery
   evidence, keeping TripoSR and Hunyuan capabilities distinct.
4. Rebuild and assess the quarantined Hunyuan image as FR-16D before considering
   any GPU activation.

Historical evidence: [2D runtime](../../phase-36/receipts/36I-2026-08-25-two-d-runtime.md),
[Blender expansion](../../phase-36/receipts/36I-2026-08-25-blender-3d-expansion.md).
