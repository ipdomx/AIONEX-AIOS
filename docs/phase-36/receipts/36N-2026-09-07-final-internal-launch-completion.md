# 36N — Final internal launch completion before external authorities

Date: 2026-09-07

Owner ordering: AWS, Bedrock, XR and payment-provider activation are the final tail. This receipt closes every remaining internal launch item that can be completed truthfully on the currently available infrastructure and credentials.

## Production baseline

- Protected PR #582 merged as `23ed8201d4f17b285e2b8efe3c4411ffeb51c4d0`; all required Backend, Docker, CodeQL, SBOM, dependency, browser, frontend, hygiene and reporting gates passed.
- The Backend-sharing runtime services were recreated from image `sha256:c42742f68a219654ec19db5dc6d44e9d323e378992d7e54ba55b3d41e60a0929` after merge.
- Backend is healthy with restart count zero; `/ready=200`; Owner External Activation page returns 200.
- Finalization is `100%`; database, Redis, Backend, runtime components, operations, release security, validation, performance, backup and approval are all `passed`; Phase 36 current batch is `COMPLETE`.
- Latest platform backup `c07003c3-113b-423a-8c27-06be7ac1debd` completed at 20,529,285 bytes with SHA-256 `623b3d739792bbee1cdf936a7bd0327a5c52b3dd794ca9ca073b13ef02145bea`; restore validation `12cbd135-00f3-41b1-aa45-eab878932421` completed with `validated=true`.

## G19 — off-host availability verification

The repository already has a GitHub-hosted scheduled Security Baseline workflow. The security audit now performs a fail-closed off-host availability probe on scheduled runs against the public portal, public API readiness endpoint and user portal, with three bounded attempts per target. This requires no new workflow-file authority and survives complete loss of the AIOS host because the runner is GitHub-hosted. The existing schedule is weekly; faster outage notification still requires external workflow-schedule authority or another monitoring account and is not misrepresented.

## G22 — communication history/current-state separation

The deployed communications statistics separate actionable deliveries from historical reconciled evidence. Current production reports actionable status as delivered-only (`254` delivered) while the preserved historical evidence is `12` old dead letters + `11` old unconfigured Push rows. No historical evidence was deleted. The rotation-window Telegram dead letter was requeued and reached delivered after endpoint ciphertext migration.

## G27 — safe cleanup

Sixteen detached anonymous test volumes and all dangling unreferenced images were removed after classification. The named Ollama model/evidence volume and tagged rollback/candidate images were retained. No blind system/volume prune was used.

## G28 — immutable commercial release manifest

Release ID `AIOS-2026-09-07-LAUNCH-23ed820` is recorded in `docs/phase-36/release-manifests/AIOS-2026-09-07-LAUNCH-23ed820.json`. The manifest binds production commit `23ed8201d4f17b285e2b8efe3c4411ffeb51c4d0`, component versions, both production Compose definitions, Alembic head `20260905_0044`, 35 runtime container image IDs and the clean source-tree state. Manifest SHA-256 is `8a5b9e54698dad6045108ac4f692d32fbd919ae76f704345069d3c2e62d5fa6e`. Component versions remain independent but the deployment now has one immutable release identity.

## G29 — realtime source debt

The obsolete Phase 36H wording that implied LiveKit provisioning was intentionally absent has been removed/reframed. The source now identifies the adapter as the non-mutating candidate/legacy surface and points to the authoritative production LiveKit runtime path, eliminating the stale implementation ambiguity.

## Growth/Social internal completion

A live Meta read-only discovery against the installed Owner credential succeeded without returning a raw token or raw Page ID. It found one real Page, `Ip Domx`, represented by the opaque provider reference `pageref://meta/sha256/45a71db7b338045099fe3884eb92b7a94159a99adc37a6996eefbbc0d3af6565`; it is advertise-ready and the inventory was not truncated. The managed-account credential contract is corrected to accept the repository's canonical `secretref://...` references while continuing to reject inline credentials and unsafe double-slash forms. After protected merge this Page can be registered as the first real managed Facebook account without persisting raw credential material.

Meta and Telegram remain the currently proven provider runtimes. Other social providers still require their platform OAuth/app/account authority; no synthetic account or live verification is fabricated.

## Mobile internal completion

Android App Links remain live with the real release certificate fingerprint. A deterministic Apple AASA generator now exists at `scripts/mobile/generate_apple_association.py`; it requires a real 10-character Apple Team ID, validates the bundle ID and emits the exact Universal Links/Web Credentials document. The current iOS project still has no Apple Development Team authority, so the AASA file intentionally remains unpublished until the real Team ID exists.

## Infrastructure authority boundaries retained truthfully

- The configured AWS S3 bucket still returns HTTP 403 on `HeadBucket`; Firebase Storage read-only probe returns `NotFound`. Therefore no off-site backup target is currently authorized. Local backups + RAID1 + restore validation remain healthy, but off-site DR cannot be claimed until a real remote bucket/object-storage authority exists.
- Multi-host HA and 1000-user realtime media capacity require at least one additional host/network failure domain. The current machine is one 12-vCPU / 62-GiB host on a 1-Gbps link; four workers on this host do not create host-level HA.
- Guest-visible storage is RAID1 + ext4 without LUKS. Full-disk encryption cannot be safely retrofitted onto the mounted production root filesystem without host migration/reprovisioning; regulated disk-encryption claims remain gated.
- Secondary RunPod's secure file exists but lacks a usable secondary API credential/endpoint/runtime image authority, so failover/overflow cannot be armed without the second-account authority.
- iOS App Store signing and additional social-platform OAuth accounts are external account authorities, not unfinished internal code paths.

AWS, Bedrock, XR and payment-provider activation remain last by explicit Owner instruction.

## Off-host watchdog acceptance trigger

The existing scheduled Security Baseline runner now executes the production availability probe for both `schedule` and explicit `workflow_dispatch` events. This allows an immediate GitHub-hosted acceptance run without adding or modifying a workflow file, while preserving the weekly independent schedule. The probe remains fail-closed for Public Portal, Public API readiness and User Portal and performs three bounded attempts per target.

## Final expanded-scope launch acceptance — 2026-09-07

- Protected PR #583 passed Backend Tests, Production Docker Build, SBOM/vulnerability, CodeQL Python/JavaScript, Dependency Security, Browser boundaries, Frontend, Core contracts, repository hygiene and Phase 36 reporting, then merged as `da7e1fd0edb94ced889d62d527f3e514257b72d0` without bypass.
- Backend and Backend-image workers were rebuilt/recreated from the merged source. Production returned to 35 running services; Backend is healthy, restart count zero, and local `/ready=200`.
- Growth/Social now has three real managed-account records instead of zero: the read-only discovered Meta/Facebook Page `Ip Domx` plus the two installed Telegram bots. External provider IDs are represented only by opaque SHA-256 references; credential fields contain only `secretref://` references and no raw provider token. Live write/spend remains disabled unless separately authorized.
- Final post-registration scheduled backup `dc151809-0b16-4770-bdc6-6a8e3533a38e` completed at 20,550,650 bytes with SHA-256 `b0bb69d90c7699203bde0c29d1fd9d468c449fee0535f8fc7a04fef37be4eadc`. The Backup Worker automatically enqueued matching restore validation `8db33b63-c4eb-4d4b-8663-a5c7e1de2b17`, which completed with `validated=true`.
- Finalization after that newer backup remains 100%: database, Redis, Backend, runtime components, operations, security, validation, performance, backup and Owner approval all pass; Phase 36 current batch is `COMPLETE`.
- Active Project/Studio/3D/Image/Video/Speech/Transcript/Dubbing/Music/Song queues are all zero. Bounded recent Backend, Backup, Communication, Project Worker and Security Scan logs contain zero ERROR/Traceback/CRITICAL/panic matches.
- Protected PR #584 then enabled immediate acceptance of the existing independent availability probe through the existing `workflow_dispatch` path, without modifying a workflow file. It merged as `426c2f4f408bbe24ea09475817db5f47e5e2b596` after the full protected matrix passed.
- Off-host GitHub-hosted acceptance run `34112890943` executed from an Ubuntu 24.04 hosted runner in Azure Central US and logged `Off-host production availability probe passed.` for Public Portal, Public API readiness and User Portal. G19 is therefore closed for independent outage detection at the repository's existing scheduled cadence.

### Remaining boundaries after all internally satisfiable work

The following are not hidden software TODOs and are not represented as completed without their real authority: multi-host HA needs a second production host/cluster plus RWX storage; off-site DR needs an authorized remote object-storage bucket (current AWS authority returns 403 and Firebase candidates return 404); guest-visible full-disk encryption needs hosting/block-device authority; Apple production association/signing needs the real Apple Team ID/signing authority; secondary RunPod needs its second-account API/endpoint/runtime authority; additional Growth/Social platforms need their real OAuth/app authorities; voice/music/high-stakes gates require the corresponding rights/certification/human-review evidence. AWS, Bedrock, XR and payment-provider activation remain explicitly deferred by Owner instruction.

## Addendum — 2026-09-08 — Off-site DR authority supplied and G20 closed

The historical statements above that no off-site object-storage authority was available were correct at the time of the 2026-09-07 closeout and are now superseded for G20 by the Owner-provisioned private Cloudflare R2 bucket. Protected PRs #592/#593/#594 implemented and hardened the R2 path; final merged runtime source is `847dacd7129174e7dcc8e4c528e5862a17371b75`.

Fresh Production backup `1b9a0849-8163-4211-b6f2-f8dd0832c4ee` replicated to R2 with full remote evidence and checksum verification. Remote restore validation `6fe89481-13e6-4cf4-b1d6-ddb7d72a78ce` completed with database, off-site and 3D validation all true. The canonical R2 credential remains root-only outside Git and transitional workspace/service copies are absent. Finalization is 100%, all ten checks pass, Phase 36 current batch is COMPLETE, and Production is 35/35 running with zero unhealthy/current restarts. G20 is therefore closed; multi-host HA and host-level disk encryption remain separate infrastructure boundaries.
