# AIONEX AIOS — New Production Server Migration Roadmap

## Old-host retirement dependency closure — 2026-10-09 (verified field evidence)

### 9 Oct owner custody correction and safe historical archives (14:31–14:55 UTC)

**OWNER CONFIRMS: the only independently retained private notes contain provider API keys; no Android/mobile application signing keystore or app-specific signing credentials are held outside OLD.** A specifically bounded root-only old-host file-status and SHA audit found the actual original Android `android-release.jks` binary **4,392 bytes**, `android-release.env` **143 bytes**, and deferred secondary RunPod environment file **420 bytes**, all mode `0600`. The three original files are **not** present at their expected NEW locations; a scoped, non-exhaustive NEW vault/migration/archival filename search found no identical application JKS. NEW root-only *metadata only*, without any secret value or original file: `/var/lib/aionex-migration/r1-management-20261008/UNRECOVERED-ORIGINAL-APP-SIGNING-20261009T1437Z.json`, SHA-256 `995f46b112149c9e3f7a24d47f15be99a44b7275c6a1ebd72fd2d8d9be95dd04`. **Critical: the original Android JKS binary must be retained through a legitimately authorized secure process before expiry. Never synthesize a new signer and claim it retains original release signing identity.** The previous exact sensitive transfer effect was explicitly platform-refused; continuing user authorization is not permission to bypass/repackage through other tools or paths.

**NEW primary production configuration cross-host SHA audit:** all **11** specifically enumerated active config/credential files are present on both hosts, with **10 byte-identical** old/new SHA-256 values. Only `.env.production` differs in whole-file hash; both have **108** variables with identical names and **107 identical values**. Its sole changed key name is `AIOS_REALTIME_PUBLIC_IP`, an expected host-specific IP setting after the cutover. No credential content or value was printed. NEW root-only receipt: `/var/lib/aionex-migration/r1-management-20261008/PRIMARY-CONFIG-PARITY-20261009T1455Z.json` SHA-256 `5084dfa2e8e60c142c79cdb56f98cdb38c66e0d0542fa126806bd5d600cc419e`. This is **allowlist parity only**, not proof that unenumerated OLD secret files or the Android keystore moved.

**Additional separately scoped old-only non-production materials now present, hash-verified, root-owned and inert on NEW:**

- Historic user-portal deliveries and 3D release assets from OLD `releases/`: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-releases/RETIREMENT-OLD-RELEASES-20261009T1436Z.tar.gz`, SHA-256 `1c6e74fca3d5aa49959c4572b9fc72337e40ee654c966c8125df886644b60b6b`, **16,118,729 bytes**, 417 archive members. Historical release only; does not supersede the LIVE NEW deployment.
- Historical FR04C1 source-safety snapshot from OLD: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-fr04c1-snapshot/RETIREMENT-FR04C1-SOURCE-20261009T1444Z.tar.gz`, SHA-256 `44717bde54f558b76ff194cd24f4c79c9f2244870e73abfb69364188935c9c0c`, **4,085,498 bytes**, **2,396 archive members**. It intentionally excludes historical database content, mypy/pycache and three source-text files triggering token/PEM-looking scan heuristics. A sample `.env.example` with no unexpected high-entropy active assignments remains; this is NOT a production secret source or a full audit of every source byte.
- Historical FR04C1 SQLite retained separately with transactional backup and actual NEW read-only `PRAGMA integrity_check = ok`, **24 tables**, never imported into production: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-fr04c1-snapshot/RETIREMENT-FR04C1-SQLITE-20261009T1445Z.tar.gz`, SHA-256 `bfe60de3fb9ea307e8fd076e3abf62b6f5290c8915ae342d959a3e14fbea495f`, 3,152 bytes. The SQLite in OLD `/opt/AIOS/data/aios.db` had exact same SHA as this already-preserved historical database.
- Six historical phase33/34c RunPod job/template/endpoint IDs from OLD `/opt/AIOS/data/phase*.txt`, without publicly disclosing values: NEW root-only `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-job-identifiers/RETIREMENT-LEGACY-JOB-IDS-20261009T1447Z.tar.gz`, SHA-256 `f63f620fb06c0e79d9e8dc5c687b8046cf2f51221a16ea4bc8ef746c69505811`, 6 files.
- Root-only consolidated verification of first three archives: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/ADDITIONAL-OLD-SOURCE-VERIFIED-20261009T144441Z.json` SHA-256 `37d78b9feaf28440348c700e06863cf0f6df7b645437b32b577d60fb62ce30b1`, verified **3/3** archives and **20,207,379** combined archive bytes.

**Other old-host handling:** TrendBost live bridge activation is now explicitly deferred at Owner discretion; its original launcher, systemd service and a Python helper were preserved on NEW, but the remote ChatGPT tunnel still depends on OLD until independently re-authorized. Do not use TrendBost bridge as a condition for *NEW AIOS production services*; disclose loss of optional legacy ChatGPT bridge on old expiry. Independent SSH and NEW-local observability are already working.

**Retirement remains `HOLD_LOSSLESS_OLD_CLONE` despite NEW production being live and independent of OLD for customer service.** The old machine's occupied root volume (~689 GiB at 14:32 UTC) was not cloned in full. Do not overwrite newer NEW live DB/assets/volumes with old backups. Historical 28 GiB scanner/runtime evidence, 17 GiB old worktrees, ~3.8 GiB Open Song weights and unreviewed possible secrets still lack exhaustive lossless preservation. Prior exact platform refusals for Open Song preflight, broad OLD inventory and Android/secondary-provider transfers remain binding; don't repeat effects via renamed archive/host/account/worker. If platform does not authorize the original-file signing key transfer, record the risk transparently before owner cancels/not-renews, seek an independently approved secure retention mechanism, and do not represent fabricated files as originals.

**Decision: HOLD_OLD_HOST_RETIREMENT.** The public AIOS application has already cut over to NEW (Oct 5); no second application migration or overwriting of live NEW customer data is authorized. Owner's reported OLD suspension is **2026-10-22** (exact provider hour/time zone unverified); Oct 20 is an internal safety buffer, not a guarantee. The separate independently developed AIONEX AI project is not part of this server-retirement change; never deploy it implicitly.

### Verified now / preserved

1. **Container coverage:** OLD has 29 running AIOS Compose container names, and every one is also among NEW's 36 running names. The additional seven on NEW include Cloudflare, realtime, Telegram and operations observation. NEW point sample: zero unhealthy/restarting containers, zero observed restart counts. Name coverage is NOT an independent API/auth/functionality or restore acceptance.
2. **Authority and durable data:** NS-10 Oct 5 recorded successful NEW-authoritative PostgreSQL, asset and project-execution vault cutover, with OLD admission authority closed, new authoritative, verified post-cutover encrypted backup and recorded validation; do not blindly replace NEW live DB or vault data with OLD snapshots. Rounded `fr06-vaults` size is approximately 233 GiB on each host; size alone is not byte parity.
3. **Local monitoring transferred:** NEW `aionex-runtime-watch.timer` runs every ~60 seconds, enabled/active with successful real timer executions (`Result=success`, `ExecMainStatus=0`); both service and timer files match OLD SHA-256. Independent immutable receipt on NEW: `/var/lib/aionex-migration/r1-management-20261008/RUNTIME-WATCH-HANDOVER-20261009T0707Z.json`, SHA-256 `9e9838b1f28a9754e831eb4112bb8d9b2b7880334afd8e76ff1cea6f06f30c4e`. Separate NEW hourly `aionex-ns12-observer.timer` already exists and must not be duplicated.
4. **Independent emergency administration:** Actual successful NEW `root` public-key SSH acceptance from the owner's mobile SSH ID was verified without OLD relay. NEW evidence `/var/lib/aionex-migration/r1-management-20261008/OWNER-INDEPENDENT-SSH-20261009T073959Z.json` SHA-256 `5765472f9170c480a7bfca167fc82d1372e2206d790a4a9d3b100e1224cb427c`. This proves independent SSH control, NOT new ChatGPT MCP control.
5. **Dormant coordinator preserved:** OLD-only, already-disabled AIONEX source-closure coordinator script and its service/timer preserved as NEW root-only archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-source-closure/RETIREMENT-SOURCE-CLOSURE-20261009T0730Z.tar.gz`, SHA-256 `e52f2b38d09ad0ef099d9afff562a1f7fffe606dd8e97868340d26c594d0a828`. Three member hashes matched source. Archive not activated; do not install/restart implicitly.
6. **Non-runtime tools preserved:** AFS source, `TOOLS`, `aionex-ops` scripts and synthetic security fixtures (44 archive members) preserved on NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-tools/RETIREMENT-LEGACY-TOOLS-20261009T0741Z.tar.gz`, SHA-256 `d9ef36e8b20b36bf5d5639e9d808f220f3c4383068925d7384806786d98cfef8`, mode 0600, not installed. Rebuildable virtualenv/cache omitted.
7. **Earlier inert source records:** NEW preserves historical Git transfer (1,045 refs/103 worktree heads), 50 uncommitted file versions plus 34 patches from 17 dirty worktrees, SQLite/operations historical snapshots, 27 acceptance receipts and 17 unpublished test files in prior hashed archives. Historical data is not automatically current source.
8. **AIOS primary configuration:** 11 specifically enumerated active production credential/config paths were verified present on NEW. *Presence does not prove content parity, functional validity or independent off-host custody.*

### Further verified 9 Oct preservation (after initial closure report)

- **Actual isolated database restore PASS:** NEW on 9 Oct restored the on-disk, SHA-matched NS10 snapshot `/var/lib/aionex-migration/NS10-FINAL-DB-20261005.dump` (SHA-256 `d973e1c4724876ac58ae8742a9a1c8778f2d94d677a6e01af059e01f8c87d6b8`) into a temporary PostgreSQL 16 container using a tmpfs data directory, **`--network none`**, no externally published ports, bounded memory/CPU, `pg_restore --exit-on-error`. Real restoration completed successfully with **176 public tables**, and the test container was removed afterwards; all **36** original NEW production containers stayed running and minute watcher showed `Result=success`. Separate NEW receipt `/var/lib/aionex-migration/r1-management-20261008/NS10-REAL-ISOLATED-RESTORE-20261009T082445Z.json` SHA-256 `09bcdcba80d525afa1a247cdaf9f928504d1068faf2a56285aa97ba95a0993a1`. This proves **only** restoring the **Oct 5 NS10 database dump**; it does **NOT** prove isolated restore of **Oct 8 or newer offsite encrypted backups**, key custody or full live-application recovery.
- **Hunyuan3D and RunPod source escrow on NEW:** Root-only **inert** archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-3d-runpod/RETIREMENT-HUNYUAN3D-RUNPOD-SOURCE-20261009T0820Z.tar.gz`, **155,095,711 bytes, 697 archive entries, SHA-256 `4b9637bad44b2348588ae7b93437e5a3a9a302c965c3fbea35beb8a53e254cd4`**. Transfer verification receipt alongside archive `TRANSFER-VERIFIED-20261009T0820Z.json` SHA-256 `50623e0d1af52f8d57cef09812716edec97b06ceb2663df89616ee092ef1c699`. Includes custom Hunyuan3D-2.1 source/assets and RunPod gateway/serverless/Docker/bootstrap code; omits nested upstream `.git` and rebuildable caches. A limited textual heuristic checked 137 source files without matching selected high-risk token/private-key patterns; **this is NOT comprehensive secret/license/production acceptance**. No containers or endpoints were changed or activated. This is **NOT** the separate `/opt/aionex-models/open-song` model weight tree, which remains unpreserved.
- **TrendBost hosting is separate from OLD bridge:** NEW reached hosted HTTPS origin and received HTTP 200 with valid TLS verification, and a separate TrendBost hosting-operator read-only `server_status` returned ONLINE. This shows the remote hosting service is reachable **without routing through the old machine**, not that a new ChatGPT management bridge has been activated. The OLD TrendBost tunnel poller remains the only verified active ChatGPT management route; NEW service remains disabled pending legitimate independent credentials + tool round-trip.
- **Uninterrupted anomaly history:** NEW locally collected NS12 observation `NS12-WATCH-20261009T080028086427Z.json` at ~08:00 UTC recorded `vip_de` process exit 28 / unavailable (one anomaly, `REVIEW_REQUIRED`). A later independent NEW HTTPS GET to the actual locale URL `https://ai.vip-e.net/de/` returned HTTP 200 (and /es/ returned 200) in under one second. Do not erase original timeout or claim zero outages; retain as transient observation pending trend monitoring.
- **Owner-held recovery keys:** The owner reports privately retained key material outside ChatGPT and authorizes rebuilding re-creatable components after OLD expires rather than paying renewal. This statement is **not** proof that the original Android JKS binary, corresponding signing certificate, every recovery token, or historical proprietary model artifact is actually available. Never log owner secrets in this public roadmap, and never assert cryptographic equivalence of replacement keys.

### Oct 9 remote R2 ciphertext proof and extra historical Git preservation

- **LATEST R2 full remote ciphertext content integrity PASS (4/4):** Production DB `backup_records` identifies backup `c07dedcc-1fc3-4cd6-beef-002d1cc48956` as the most recent completed backup as of Oct 9 ~11:55 UTC, generated **2026-10-08 17:01:45 UTC**. Authenticated *read-only* Cloudflare R2 S3 `GET` on NEW streamed and SHA-256 hashed all four entire encrypted remote objects, comparing independent `offsite_evidence.encryption.ciphertext_size_bytes` and `ciphertext_sha256`. All sizes and SHA-256 hashes matched: database **21,481,844 bytes**, manifest **1,973**, 3D snapshot **54,937,868**, platform asset snapshot **54,937,868**. All use AES-256-GCM; the difference of 268 bytes against recorded inner source sizes is the documented external encryption-envelope overhead, not a mismatch. Root-only NEW receipt: `/var/lib/aionex-migration/r1-management-20261008/R2-OFFSITE-OBJECTS-VERIFIED-20261009T115253Z.json` SHA-256 `20b660c09917730d11c317c50a5f76af6c9e6bbac756fb8d2b25de9edb0dd115`. **Verified:** remote existence, remote complete encrypted bytes and hash integrity; production unchanged, secret values neither printed nor copied.
- **Encryption key identity availability on NEW:** The root-owned NEW backup encryption keyring is mode `0400`, its sole active `key_id` was independently matched (by ID only, with no secret output) to the `key_id` in **all four** Oct 8 offsite encryption manifests. This verifies local key identity existence, **not** successful full decryption, recent offsite database+asset restoration, or independent external key escrow/custody. The existing Oct 8 DR record `df8476a5-a779-43b4-9862-6f68ef288ed0` says `restore_validation completed/validated/offsite_validated=true` and `dry_run=true`; do not invent a separately observed fresh real restore from those flags. The *separate* Oct 5 NS10 database dump was actually restored in a disposable network-isolated PostgreSQL container on NEW on Oct 9 (176 public tables), as recorded above.
- **Hunyuan3D full nested Git history additionally preserved:** Previously archived on-disk Hunyuan/RunPod source excluded the 154 MiB nested `.git` directory. Now NEW has separate inert root-only archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-3d-runpod/RETIREMENT-HUNYUAN3D-GIT-HISTORY-20261009T1200Z.tar.gz`, size **154,278,445 bytes**, 46 entries, SHA-256 `a923dc6fb6f9d0ec83c8001f24ad66efe01d664e4f4143cfaf6befc2d48c5779` equal OLD. A real disposable NEW reconstitution using *both* the source archive and `.git` history completed: Git HEAD `82920d643c0dc2f7bfd7255f45f62d386edfe60c` verified, Git connectivity `fsck` PASS, **three** original dirty worktree entries retained; temporary files removed. NEW verification receipt `HUNYUAN3D-GIT-HISTORY-VERIFIED-20261009T115833Z.json` in the same protected directory SHA-256 `c0ee38cfc7fd77e85211e196b4978e7e4388bd3feae5bb3cb5692fea616e6009`. This is unrelated to missing Open Song model weights.
- **TrendBost bridge code ready but NOT connected:** Exact OLD/NEW launcher SHA and unit SHA parity preserved. NEW `sh -n` and `systemd-analyze verify` both PASS; NEW service `inactive/disabled`, OLD bridge remains `active`. Original credential-source inspection was platform-safety-refused: no repackage/reroute, no blind second poller, and no false claim that new authenticated tunnel is live. The separately hosted PHP operator remains reachable via HTTPS from NEW. A legitimately provisioned *new* independent credential and confirmed tool round-trip are still missing. After OLD expiry the existing ChatGPT-bridged control may stop even while the hosted TrendBost operator remains online.
- **Persistent handoff:** GitHub <https://github.com/ipdomx/AIONEX-AIOS/issues/884> is the owner-approved **no-renewal** retirement checklist and includes these exact new evidence references. User plans to let OLD contract expire by **2026-10-22**, but no automatic early stop/wipe/provider cancellation is authorized. Remaining untouched hard gates: original Android signing binary escrow/official recovery, deferred secondary RunPod secret, original Open Song weights or licensed reconstruction, fresh isolated latest-offsite decrypt+restore and external key custody, independent TrendBost/ChatGPT bridges, real reboot startup and relevant authenticated/NS14A releases. Preserve no-disclosure, no duplicate legacy tunnel, and no replacement of NEW live production state.

### Remaining blockers (do not mark complete)

- **TrendBost bridge:** TrendBost hosting endpoint answered independently via its own operator connector, but OLD `trendbost-mcp-bridge-tunnel.service` remains active and NEW is installed but **disabled/inactive**. Executable and systemd unit hashes match exactly on OLD/NEW (binary SHA `ae852b18ced97d8bd3320e7429d8c3709b5b60dddee19baef8895c1cb5d9f3d2`, unit SHA `f4860698d9d2756d80d0e6d5f223dd2c33e720fcd49be7d08faca50ed495f992`). The old bridge requires a control-plane credential, whose source was not approved for inspection; no successful NEW authentication/connection or OLD disconnect has occurred. This is a **separate TrendBost service** and requires an authorized new credential or approved migration, verified new-tunnel polling/tool round-trip, then measured old disconnection. Do not run both blindly, assume hosted MCP means old bridge is unneeded, or silently deactivate.
- **New ChatGPT MCP:** NEW tracked `ops/mcp2/server.py` has all 28 tool handlers and a local root-only runtime key for independent tunnel `tunnel_6ac82b37d9508191a504553fafe701a7`. NEW `tunnel-client` returned **zero registered profiles**, so it is NOT active. Tunnel profile initiation was blocked by platform safety check at approximately 2026-10-09 06:24 UTC. Support case **16766780** reports Full MCP write/modify not available on user's Pro tier. Neither Workspace reuse nor an API key alone fixes write entitlement. Do not circumvent previously refused configuration execution via alternate tool, host, script or worker; allow an independent SSH-based operational process rather than claiming ChatGPT management independence.
- **Deferred secret custody:** Original Android release signing keystore/config and secondary RunPod provider config were not verified copied onto NEW; requested transfer was platform-refused. **Never synthesize a replacement signing identity** and claim upgrades will remain compatible: preserve the original keystore securely or use supported signing-key recovery/rotation procedure. Secondary provider credential can only be reissued through its authorized provider/account, not reverse-engineered. Keep providers deferred and never print secret values.
- **Open Song local model materials:** OLD `/opt/aionex-models/open-song` occupies ~3.8 GiB, 20,970 files and six symlinks; that path is absent on NEW. These data were not bind-mounted on the three inspected OLD production services, but may be important for reproducibility/future offline operation. A sensitive-source preflight was blocked; transfer/recreation is NOT complete. Only preserve after permitted provenance/sensitivity review, or independently reconstruct from approved upstream models pinned to license/checksums without misrepresenting equivalence.
- **Historical evidence/caches:** OLD has approximately 28 GiB under `docs/project/runtime` and 17 GiB of worktrees, largely historical test/security/build artifacts; selected critical records are preserved, full archival inventory and retention classification are not certified. Do not equate lossless OLD retirement with transferring every rebuildable cache.
- **Recovery / release:** The Oct 5 NS10 database snapshot passed an actual NEW-only network-isolated PostgreSQL restore (176 tables) on Oct 9; **Oct 8 Cloudflare R2 encrypted ciphertext bytes and SHA-256 are now independently verified 4/4 and all four needed key identifiers exist in the NEW keyring**. The Oct 8 automated DR validation is recorded `completed/dry_run=true`, but **a separately witnessed real isolated restoration of that latest offsite encrypted backup, external encryption-key custody and whole-application recovery remain NOT proven**. Full authenticated browser/TCP/reconnect tests, VIP security publication, local PR #877 publication and some source reconciliation remain HOLD or refused. The 72-hour NS-12 elapsed threshold does not substitute for complete observation coverage. Check latest NS-12 receipts and source CI rather than backfilling successes.
- **Cross-project completeness:** Other OLD jobs, integrations or address-based dependencies must be attested before full hardware retirement. No blanket disable/wipe/cancellation merely because AIOS itself is live on NEW.

### Safe completion sequence and future assistant handoff

1. Read this map **together with** live protected-main SHA, NS-10 cutover evidence, newest NEW host monitor and migration receipts. Always prefer recent live evidence over old screenshots and Oct 7 source-version references.
2. Complete only genuinely *permitted*, scoped, reversible actions; hash and read-back verify copies before relying on them. If an exact effect was platform refused, log `BLOCKED` and require legitimate authorization resolution rather than repackaging the same action. Do not fabricate files/keys/models.
3. For TrendBost, explicitly retain service ownership, gain an authorized independent new-host tunnel credential and test new-host roundtrip before stopping the OLD bridge. Never merge this with AIOS production credentials.
4. Resolve Android signing key custody and secondary provider deferral independently. Preserve unique records; treat non-reconstructable keys differently from rebuildable runtime caches.
5. Prove isolated recovery with independent key custody, ownership of admin access, current data backup, authenticated journeys, and latest release gates. Obtain owner sign-off and separately confirm external addresses, provider callbacks and old-only jobs no longer depend on OLD.
6. **Only then** mark `OLD_RETIREMENT_READY_FOR_OWNER_APPROVAL`. Actual OLD wipe, provider cancellation or shutdown requires explicit, separate owner authorization. Until then `HOLD_OLD_HOST_RETIREMENT` remains authoritative.

## Current authoritative state — 2026-10-07

Status: CUTOVER_COMPLETE_NEW_SERVER_AUTHORITATIVE_NS12_OBSERVATION_ACTIVE_BACKEND4C6_VIP1FED_NS15_RECONCILIATION

- The new Debian 12 production server is the authoritative public runtime.
- The old production server is retained intact as the rollback anchor and must not be retired before the original NS-12 observation gate and explicit Owner approval.
- Protected GitHub `main` is currently `1fedff22300c1abb699439f32409bbb10ccb7ce7`. Backend/new-server runtime remains the accepted application release `4c6ae50091fb568b491eacbffa0fec53a444092d`; the separate shared-hosting VIP user portal is published from `1fedff22300c1abb699439f32409bbb10ccb7ce7` after PR #878.
- PR #875 closed the earlier VIP dependency alerts, and PR #878 subsequently moved VIP Sharp to 0.35.5 for GHSA-wq5f-xc86-pv6w. Exact-head and post-merge CI are PASS, the published VIP package has `npm audit --omit=dev = 0`, and Dependabot reports **0 open alerts** after reindex. Four source-manifest-only Trivy Docker-module alerts remain documented as evidence-backed not-used dismissals; this is not an absolute-security claim.
- The currently deployed application release is `4c6ae50091fb568b491eacbffa0fec53a444092d`. Exact-source backend/image-derivative/frontend images were rolled out on the new production server after protected-main CI PASS; Sharp runtime is 0.35.5 with libvips 8.18.7, rollback tags are preserved, public/user/API/Owner smoke is PASS, production unhealthy/restarting counts are zero, and maintenance admission is reopened at generation 50.
- The active `ai.vip-e.net` user portal remains on its established shared-hosting route and is now published from protected main `1fedff22300c1abb699439f32409bbb10ccb7ce7`: pre-deploy backup created, rsync dry-run reviewed, package-owned SHA-256 parity `362/362`, all six locale roots plus login/projects/API checks HTTP 200, and no DNS/Cloudflare Tunnel/backend/Owner-policy mutation.
- Canonical FR-09 1,000-user acceptance is PASS on the new server; the staged authenticated-read growth envelope through 5,000 sessions is recorded as a synthetic capacity envelope, not a claim of 5,000 simultaneous heavy AI/GPU generations.
- NS-12 observation started at `2026-10-05T16:43:26Z`; the earliest 72-hour completion is `2026-10-08T16:43:26Z`. Application updates do not reset this original window.
- FR-07F conversation anti-stall/reconnect protection is merged from PR #872 and remains deployed/verified in release `4c6ae50091fb568b491eacbffa0fec53a444092d`. Runtime source hash matches the protected source; heartbeat=10s, stale-running fail-closed threshold=180s, provider hard timeout=150s, and unauthenticated policy routing is live/fail-closed. Public smoke is PASS. The broader NS-14A fault matrix (mid-stream transport drops, auth refresh/expiry, repeated reconnect and terminal-event loss) remains required before final release closure.
- NS-15 tracked reconciliation is being refreshed to the split current truth: protected main/VIP portal `1fedff22300c1abb699439f32409bbb10ccb7ce7`, backend/new-server runtime `4c6ae50091fb568b491eacbffa0fec53a444092d`, and the original NS-12 observation window unchanged. The retained append-only runtime journal remains the execution ledger; generated STATE/PROJECT-REPORT are updated only through project_hub.

### Current continuation transport

The approved continuation path is **MCP2 management entry -> approved SSH administration channel with strict host-key verification -> new production server -> clean exact-SHA checkout/worktree**. The tracked map intentionally does not contain the new host IP, SSH private-key path/material, credentials, or raw environment secrets.

## Historical migration baseline — 2026-10-04

The block below is the original pre-migration baseline and must not be treated as the current runtime state after cutover.

Status at that time: NEW_SERVER_PROVISIONED_PROVIDER_HARDWARE_VERIFIED_AWAITING_INDEPENDENT_HOST_AUDIT

### Live authority and continuity rule

Before any continuation, operator or assistant action must reconcile all of the following rather than trusting a screenshot or stale paragraph:

1. protected GitHub main and the exact candidate/head commit SHA;
2. the latest retained migration/runtime checkpoint and evidence;
3. the actual new-host source SHA, running image identities, database/schema state and health;
4. current protected CI for the exact head being considered;
5. rollback state on the old server.

If these disagree, the discrepancy is recorded as documentation drift and live/GitHub evidence wins until canonical reconciliation. A stale map must never trigger a blind pull, reset, deletion, deployment, replay or provider action.

The new dedicated server has been purchased and access details have been received. The provider control panel shows Debian 12 x86_64. Provider technical support has confirmed all of the following:

- All 4 x 1.92 TB NVMe drives are detected correctly.
- The drives are configured as RAID 10.
- The RAID array is healthy, fully synchronized, and has no degraded disks.
- The server has the full 128 GB RAM.
- Both AMD EPYC 7313 CPUs are detected correctly.

No application data has been uploaded to the new server. Migration has not started. The existing production server remains the source of truth and must remain online and unchanged until the cutover, observation, rollback, and retirement gates below are all satisfied.

Expected new-server profile:
- Dual AMD EPYC 7313, 2 x 16 physical cores, 32 physical cores total.
- 128 GB RAM.
- 4 x 1.92 TB NVMe in RAID 10, approximately 3.84 TB usable before filesystem overhead.
- 1 Gbps unmetered network subject to provider network-protection/fair-use policy.
- Debian 12 x86_64.
- User-Responsible management.
- No cPanel, Webuzo, Softaculous, or WHMCS.
- Full root and out-of-band IPMI/recovery access expected.

Never store passwords, SSH private keys, IPMI credentials, recovery keys, provider secrets, raw environment files, or customer data in this roadmap, Git, receipts, or chat logs.

## Migration invariants

1. The old production server remains authoritative until explicit cutover acceptance.
2. No destructive change, wipe, cancellation, or cleanup of old production before rollback-retirement approval.
3. Provider confirmation is not enough by itself; an independent read-only host audit must pass before the first data upload.
4. No blind copying of secrets. Secrets move only through approved secure handling and are never committed.
5. RAID is redundancy, not backup. A separate encrypted backup and tested restore path is mandatory.
6. Public traffic is not switched until the new server passes isolated application acceptance.
7. The new server has a different public IP. Every direct-IP dependency, allowlist, callback, webhook, monitoring target, and external integration must be inventoried before cutover.
8. Prefer the existing Cloudflare Tunnel architecture so public hostnames are not tightly coupled to the server IP.
9. The old and new servers run in parallel during migration and observation.
10. Every phase ends with a documented PASS, HOLD, or ROLLBACK decision.
11. No paid-provider fanout or real customer data is used in load tests unless separately approved.
12. Deferred scope remains deferred: XR, unconnected/secondary providers, payments/store-app activation, and other explicitly deferred items are not silently reactivated by the migration.

## NS-00 — Independent pre-migration host audit

Run before uploading any application data.

Verify from the new server itself:
- Debian 12 release and kernel.
- CPU model, sockets, cores, threads, NUMA topology.
- Total RAM, available RAM, memory topology/ECC visibility where exposed.
- All four NVMe devices, model/firmware/health, without publishing sensitive hardware identifiers.
- RAID 10 membership and health.
- Array fully synchronized, no rebuild, no degraded member.
- Actual usable filesystem capacity consistent with RAID 10.
- Partition table and boot layout.
- Boot redundancy and recovery path.
- Filesystem type, mount options, free space, and inode capacity.
- Network interfaces, link state, negotiated speed, gateway, DNS resolution, and time synchronization.
- Root access works.
- IPMI/out-of-band console access works independently of SSH.
- No unexpected hosting panel or preinstalled stack is present.
- No unexplained public listeners.

Exit: independent OS/hardware/RAID/network baseline PASS. If anything differs from the order or provider confirmation, stop before upload and have the provider correct it.

## NS-01 — Host security baseline

Before installing the application:
- Apply Debian 12 security updates using a controlled maintenance step.
- Record the kernel and package baseline.
- Set final hostname, timezone, NTP/chrony/systemd-timesyncd and verify synchronized time.
- Establish approved SSH key access.
- Establish least-privilege admin/sudo path and emergency root recovery.
- Harden SSH and disable weak authentication/algorithms according to project policy.
- Configure firewall/nftables with deny-by-default inbound policy.
- Expose only explicitly required management and application paths.
- Configure fail2ban or equivalent brute-force protection.
- Configure unattended security updates consistent with maintenance policy.
- Configure journald/logrotate retention and disk-growth controls.
- Verify no accidental public DB, Redis, Docker API, metrics, or admin listeners.
- Keep IPMI credentials outside the project repository and application environment.
- Confirm the provider network and reverse DNS requirements, if any.

Exit: hardened host with a proven independent recovery path.

## NS-02 — Storage and filesystem operating model

Before copying production state:
- Confirm RAID 10 health monitoring.
- Enable periodic RAID health checks/scrubs where appropriate.
- Confirm NVMe SMART/health monitoring.
- Choose the final filesystem and mount layout before bulk data transfer.
- Define separate locations for application source, Docker data, database volumes, uploads/assets, logs, build/cache data, and migration staging.
- Preserve large free-space headroom; normal production should not be planned near the old server's 95% usage.
- Target operational disk warnings before 70%, escalation at 80%, urgent remediation before 85%.
- Define cleanup rules for build caches, stale worktrees, temporary artifacts, old images, and logs.
- Keep backup copies off the same server/RAID.
- Confirm backup target capacity and encryption.

Exit: storage layout documented, health monitoring available, and independent backup destination ready.

## NS-03 — Base runtime installation

Install only required supported components:
- Docker Engine.
- Docker Compose v2.
- Git and deployment utilities.
- Required monitoring/storage/network tools.
- Cloudflared package and service files prepared but not used for production cutover yet.
- Host Node/Python tooling only when genuinely required; prefer project containers for reproducibility.
- Required systemd units only from reviewed project source.
- No cPanel or unrelated hosting stack.
- Record all installed versions.

Exit: clean reproducible host runtime with no production traffic.

## NS-04 — Source and configuration preparation

- Fetch the canonical ipdomx/AIONEX-AIOS repository from protected main.
- Use the approved new-server production root.
- Verify exact commit SHA and clean checkout.
- Do not copy a dirty old-server checkout as the source of truth.
- Validate Compose files and deployment manifests before startup.
- Prepare required directories, permissions, ownership, and file modes.
- Migrate configuration through secure secret handling.
- Never commit secrets or raw env files.
- Inventory all old-IP dependencies before changing them:
  - firewall allowlists,
  - provider callbacks,
  - webhooks,
  - monitoring targets,
  - outbound allowlists,
  - third-party dashboards,
  - backup endpoints,
  - SSH trust/known-host references where operationally relevant.
- Preserve all current deferrals and provider-live safeguards.

Exit: source/configuration ready with no public traffic and no paid-provider side effect.

## NS-05 — Pre-migration backup and rollback package

Before copying mutable production state:
- Create a fresh encrypted production backup using the accepted backup path.
- Create a consistent PostgreSQL backup/snapshot and verify integrity.
- Capture required persistent volumes, uploads, assets, and metadata.
- Capture service topology and deployment manifests without exposing secrets.
- Record:
  - source commit SHA,
  - container image identities/digests where available,
  - database schema/migration level,
  - application release/version,
  - backup timestamp,
  - RPO reference point.
- Verify the backup can be read.
- Perform an isolated restore test before relying on it.
- Establish rollback owner and rollback trigger criteria.

Exit: independently restorable pre-migration package PASS.

## NS-06 — Initial bulk migration while old production stays live

- Transfer immutable and large data first.
- Use integrity-preserving copy methods and checksums/manifests.
- Copy application uploads/assets and persistent storage.
- Restore a database copy to the new server in isolated mode.
- Do not blindly copy ephemeral caches.
- Restore Redis persistent state only if required by the application contract.
- Bring up PostgreSQL, Redis, application containers, and supporting services on the new server without public production traffic.
- Keep old production accepting normal traffic.

Exit: isolated complete replica available for testing.

## NS-07 — Isolated application acceptance

Validate the new server before any public cutover:
- Expected containers start successfully.
- Intentionally drained services remain intentionally drained.
- No running container is unhealthy.
- Backend health/readiness endpoints pass.
- PostgreSQL connectivity, schema, migrations, row/data integrity, indexes, and extensions are correct.
- Redis connectivity and queue/session semantics are correct.
- Nginx public/private origin layout is correct.
- Public portal, user portal, and Owner portal routes work.
- Authentication and authorization work.
- Owner controls, suspension, revocation, policy limits, and audit trails work.
- Multiple projects and multiple conversations work.
- Save/resume and isolation work.
- Upload/download and asset isolation work.
- WebSocket/event-stream behavior works.
- Six-language, RTL, dark mode, mobile, Safari, and accessibility checks run where applicable.
- Browser E2E, security baseline, source validation, and final validation suites pass.
- Provider connectors remain synthetic/fail-closed unless a separately approved real-provider acceptance is required.
- Resource/provider credit alerts and monitoring contracts work.

Exit: isolated new-server application acceptance PASS with no unexplained regression.

## NS-08 — Cloudflare and network cutover preparation

- Inventory all current DNS records, Tunnel routes, Access policies, callbacks, webhooks, monitoring endpoints, and direct-IP dependencies.
- Preserve current Cloudflare policy; migration is not permission to redesign Access or DNS.
- Prepare the new server as a reviewed Cloudflare Tunnel connector/origin.
- Keep the old connector/origin available for rollback.
- Verify the user portal, public site, and Owner portal private/public routing boundaries.
- Update direct-IP allowlists or callbacks deliberately, one by one, with evidence.
- Reduce DNS TTL only where a direct DNS switch is genuinely needed.
- Test the traffic-switch and rollback method before the maintenance window.

Exit: reversible traffic-switch plan proven.

## NS-09 — Rehearsal and final-delta plan

- Perform a complete rehearsal restore from accepted backup.
- Measure restore duration.
- Reconcile DB integrity, file counts, hashes/manifests, and persistent-volume completeness.
- Define the final maintenance/write-drain window.
- Define which queues/jobs must drain or stop accepting new work.
- Confirm no ambiguous in-flight provider jobs.
- Define final database snapshot and file-delta synchronization procedure.
- Confirm rollback can be executed without relying on the new server.

Exit: signed-off cutover checklist and proven rollback.

## NS-10 — Production cutover

Sequence:
1. Enter the controlled maintenance/write-drain window.
2. Gate new mutable work on the old server using accepted controls.
3. Allow in-flight work and queues to reach the defined safe state.
4. Take final DB backup/snapshot.
5. Perform final delta sync of persistent files/assets.
6. Restore/apply final delta on the new server.
7. Re-run migrations, DB integrity, readiness, permissions, and filesystem checks.
8. Start the new production stack.
9. Verify internal health before public traffic.
10. Activate the new Cloudflare Tunnel connector/origin or other preapproved traffic switch.
11. Run real-public-hostname smoke tests.
12. Verify authentication, Owner portal, user portal, projects, conversations, uploads, queues, DB, Redis, and critical APIs.
13. Monitor closely.
14. Keep the old server intact and ready for rollback.

Exit: production traffic successfully served by the new server while rollback remains available.

## NS-11 — Immediate rollback criteria and procedure

Rollback immediately for any material:
- database inconsistency or missing data,
- authentication/authorization regression,
- persistent 5xx/availability failure,
- broken Cloudflare routing or Access,
- queue duplication/loss or unsafe replay,
- corrupted upload/download,
- billing/entitlement inconsistency,
- critical security regression,
- critical monitoring/backup failure that makes continued operation unsafe.

Rollback sequence:
- Stop new writes on the new server.
- Route traffic back to the old server using the preplanned switch.
- Confirm old-server health before reopening writes.
- Preserve new-server evidence; do not wipe it.
- Reconcile data written during the attempted cutover before any second attempt.

## NS-12 — Post-cutover observation

Keep both servers for at least 72 hours, and longer if operational evidence requires it.

Monitor:
- HTTP/API error rate and latency.
- Authentication and authorization failures.
- PostgreSQL health, connections, locks, replication/backup state where relevant.
- Redis memory, latency, persistence, and queue behavior.
- Queue depth and wait time.
- Container health/restarts.
- CPU/load and scheduler pressure.
- RAM/swap/OOM events.
- RAID/NVMe health.
- Disk space, filesystem growth, IOPS and latency.
- Network throughput and 1 Gbps ceiling.
- Cloudflare Tunnel health.
- Scheduled jobs and monitoring.
- Backup success, age, and restoreability.
- Security/update/audit findings.

Exit: stable observation window with no unresolved critical issue.

## NS-13 — Capacity acceptance and 5,000-user growth readiness

The new hardware is intended to provide significant headroom, but 5,000 users does not mean 5,000 simultaneous heavy AI/GPU generations on one host.

Required:
- Re-run the canonical 1,000 authenticated-user / multiple-project / multiple-conversation acceptance on the new production-equivalent configuration.
- Characterize safe staged synthetic concurrency, as appropriate, across 500, 1,000, 2,500, and up to 5,000 sessions/projects without uncontrolled paid-provider fanout.
- Measure p50/p95/p99 latency.
- Measure request rate, error rate, queue depth/wait, CPU, RAM, swap, DB connections/locks, Redis, disk IOPS/latency, and network throughput.
- Preserve tenant isolation, zero lost jobs, and zero duplicate terminal executions.
- Abort escalation on correctness loss, rising 5xx, DB/queue saturation, swap thrash, unsafe provider fanout, RAID/storage pressure, or network saturation.
- Record a safe operating envelope rather than claiming unlimited capacity.
- Treat the 1 Gbps network as a possible future bottleneck.
- Define horizontal scale-out triggers:
  - additional application/worker nodes,
  - dedicated database node,
  - dedicated Redis/queue node,
  - external object storage/CDN for large assets,
  - specialized media/AI workers.
- Scale horizontally before a single-host bottleneck becomes a production incident.

Exit: measured capacity report with clear limits and scale-out triggers.

## NS-14 — Monitoring and ongoing operations

Required alerts:
- RAID degraded/rebuild.
- NVMe SMART/health.
- Disk and inode pressure.
- CPU/load.
- RAM/swap/OOM.
- Container unhealthy/restart loops.
- PostgreSQL availability/resource pressure.
- Redis availability/resource pressure.
- Queue depth/wait/failures.
- Public endpoints and Cloudflare Tunnel.
- Backup success/age/restoreability.
- Provider credit/usage alerts.
- Security updates/audit findings.

Maintain cleanup for:
- stale worktrees,
- build caches,
- obsolete images,
- old temporary migration files,
- logs and diagnostics,
while preserving evidence required by project policy.

## NS-14A — Client response and streaming resilience

This is a release-scope requirement prompted by the observed class of UI failure where a long response can stop with a generic “streaming interrupted / waiting” state. The external ChatGPT client failure is not evidence that AIOS itself has the same bug, but the analogous failure mode is now explicitly in AIOS scope and must be tested before final release closure.

Required behavior for every AIOS long-lived response, stream, live progress feed, or equivalent asynchronous delivery path:
- Never silently hang forever. Use bounded idle/overall timeouts plus heartbeat/progress semantics where a long-lived transport is used.
- Preserve the accepted request/job identity independently of the client transport.
- A network drop, app background/foreground transition, proxy timeout, server restart, or client reconnect must not create a duplicate billable provider request or duplicate terminal execution.
- If the transport is resumable, reconnect from an acknowledged cursor/sequence/event id with bounded exponential backoff and jitter.
- If the upstream/provider stream cannot be resumed, the client must fall back to durable job/status retrieval rather than pretending the partial stream completed.
- Duplicate/replayed chunks or terminal events must be idempotently de-duplicated.
- UI states must distinguish connecting, streaming/running, reconnecting, recovered, completed, cancelled and failed; a generic indefinite spinner is not acceptable.
- Partial content/progress that is safe to retain should remain visible after reconnect.
- Authentication/session expiry during reconnect must fail closed and present a recoverable user action without losing the underlying durable job when policy permits.

Acceptance must cover at least: mid-stream TCP drop, Cloudflare/proxy interruption, client app background/foreground, network change, repeated reconnect, duplicate events, server/container restart, auth refresh/expiry, terminal-event loss, and fallback polling/status recovery.

Status: MERGED_DEPLOYED_RUNTIME_STRUCTURAL_PASS_EXTENDED_FAULT_ACCEPTANCE_PENDING. PR #872 exact head `d17c54530c9142f04bbf9aab50a1df01f5abe926` merged as `9dd7a79d3b590a25675d5209de14b5176cba7f7f` and is deployed in release `960dab80fe8ec27b1e8bf59425b766e03f9b9783`. Runtime structural/public smoke is PASS; the complete NS-14A disconnect/reconnect fault matrix remains required before final acceptance.

## NS-15 — Canonical documentation reconciliation

After stable cutover:

### Exact-SHA new-server operating discipline

The accepted operating path is explicit and immutable-SHA based:

1. MCP2 may land on the retained management/old host; do not infer from the MCP name that the process is executing directly on the new host.
2. Reach the new host only through the already-approved SSH migration/administration channel with strict host-key verification; never place host IPs, private-key paths/material, credentials or raw host secrets in tracked docs.
3. Resolve the exact protected-main or reviewed PR head SHA from GitHub before mutation.
4. On the new host, fetch the required ref and verify the exact SHA. Do not use a blind `git pull` as the release decision.
5. Build/test from a clean detached worktree or clean checkout bound to that immutable SHA. Dirty source is never release authority.
6. Protected CI evidence is valid only for the exact head SHA it tested. A newer commit requires fresh exact-head acceptance.
7. Before rollout, preserve rollback source/image identities and revalidate maintenance/admission authority.
8. After rollout, verify runtime source/content hashes or image identities, database/schema expectations, public/authenticated health and relevant feature smoke against the accepted SHA.
9. Keep the old server and rollback artifacts intact until the observation/retirement gates and explicit Owner approval are satisfied.

This is the continuity method to use if a conversation is interrupted: recover the last accepted SHA and evidence first, then continue from the new host without replaying already-performed effects.

### Update ledger and map reconciliation policy

Every material project transition must be retained, including unsuccessful work. The minimum record is: UTC time, phase/batch, exact source/candidate SHA, target environment/host role, action, outcome, evidence reference/hash where available, whether production was mutated, and the explicit next action.

Allowed operational outcomes are at least: IN_PROGRESS, PASS, FAIL, BLOCKED/HOLD, PENDING_RETRY, ROLLBACK and COMPLETE. Failed or superseded attempts are evidence and are not overwritten to make the history look clean.

The append-only runtime journal/checkpoint is the immediate execution ledger. The canonical PLAN/roadmap is the durable reviewed summary and is reconciled at material checkpoints; transient minute-by-minute CI polling does not require a Git commit for every poll. Generated STATE.json and PROJECT-REPORT.md are updated through `scripts/project_hub.py`, never hand-edited.

Before starting a new continuation, read the canonical map, latest checkpoint/journal, GitHub protected state and live new-host evidence. If any “done / failed / still required” state is absent or contradictory, record the drift before further mutation.

- Update PLAN and canonical project state through scripts/project_hub.py.
- Never hand-edit generated STATE.json or PROJECT-REPORT.md.
- Record the new production hardware profile, Debian 12 baseline, source SHA, images, DB schema, migration/cutover timestamp, and acceptance evidence.
- Update recovery, backup, monitoring, and rollback runbooks.
- Confirm the old public IP is no longer required by any DNS record, allowlist, callback, webhook, monitoring target, or provider integration.
- Never store credentials in tracked documentation.

Exit: source, production, documentation, monitoring, and recovery evidence agree.

## NS-16 — Old-server retirement

Only after all prior gates and explicit Owner approval:
- Take final archival backup of old production.
- Independently verify new-server backup/restore.
- Confirm no user traffic, scheduled job, provider callback, monitoring target, or Cloudflare route still depends on the old server.
- Rotate/revoke old-server-only credentials and SSH trust as appropriate.
- Remove the old Cloudflare Tunnel connector only after new-connector stability is proven.
- Preserve required audit/history evidence.
- Contact provider Billing to cancel the old server only after explicit Owner approval.
- Never cancel early merely to save cost.

## Migration complete definition

Migration is complete only when all are true:
- Independent new-host audit PASS.
- Security/storage/runtime baseline PASS.
- Source/configuration/data migration verified.
- New server serves public production traffic.
- Required production acceptance PASS.
- Canonical 1,000-user capacity acceptance PASS on the new server.
- 5,000-user growth envelope and horizontal scaling triggers are documented honestly.
- Backup/restore/recovery and monitoring PASS.
- Old-server rollback observation window completes successfully.
- Client response/stream delivery resilience acceptance PASS, including reconnect/fallback without duplicate execution or provider charge.
- Canonical project documentation is reconciled.
- Owner explicitly approves retirement of the old server.

Until then the status remains MIGRATION_IN_PROGRESS_NOT_COMPLETE.
