# Phase 36 Receipt — External Activation Ledger + Owner/VIP UI

Date: 2026-09-04
Branch: `feat/external-activation-ledger-20260904`
Base: `07e8e656e827a7b9cafe06f14e5f3b779b9b9ae2`

## Scope decision

Current closeout explicitly excludes direct Apple Pay, App Store publication, and Google Play publication. The authoritative Phase 36 registry remains unchanged; `store-signing-and-publication` is surfaced as `excluded_current_scope` rather than rewritten or falsely satisfied.

## Backend

Added a read-only Super Owner external-activation ledger at:

- `GET /api/v1/owner/external-activation`

The ledger has no generic mutation/override endpoint. It derives status from the authoritative Phase 36 registry and from existing live evidence sources where an automatic determination is valid.

Current production evidence sampled before merge:

- Registry external gates: 16
- In-scope gates after the current store-publication exclusion: 15
- Satisfied by live runtime evidence: 1 (`live-payment-provider-credential`)
- Internally fail-closed but external evidence still pending: 6
- Blocked on genuine external facts/infrastructure/authority: 8
- Live payment evidence: Stripe/Mada live-ready
- Paid launch provider finance baseline records: 0/3 for connected OpenAI, Mistral, and DeepSeek launch providers; no funded balances were fabricated
- Public LiveKit/STUN/TURN/SFU production infrastructure was not present and was not falsely marked ready

## Owner UI

Added `/owner/external-activation` and registered it in Owner navigation and completion-page inventory. The page shows:

- live counts by gate status,
- each external fact and required evidence,
- implemented internal fail-closed controls,
- sanitized live evidence,
- affected Phase 36 batches and capability IDs.

The page is read-only and protected by the existing Super Owner route boundary.

## VIP user UI

Updated the governed Studio experience on `ai.vip-e.net` source to show capability activation state visibly instead of relying on hidden tooltips:

- currently available capability-family count,
- external-activation-waiting family count,
- distinct external-gate count,
- per-family Ready / External activation badges.

The UX consumes the existing governed user Studio catalog; it does not expose Owner-only finance details or introduce a public bypass. Strings were added for Arabic, English, French, German, Spanish, and Turkish.

## Validation evidence

Backend:

- fresh PostgreSQL 16 migration zero -> `20260825_0043`: PASS
- targeted external-activation + Owner dashboard contracts: `21 passed`
- Ruff: PASS
- Mypy: `249 source files`: PASS
- full backend suite: `1102 passed, 0 failed`

Core:

- full core suite after registering the new Owner page in `OWNER_PAGE_BATCH`: `857 passed, 0 failed`

Owner frontend:

- API-contract check: PASS
- TypeScript type-check: PASS
- Next production build: PASS
- `/owner/external-activation` generated successfully

VIP frontend:

- integrity: `96 files, 6 complete locales, no simulated data markers`: PASS
- TypeScript type-check: PASS
- ESLint with zero warnings: PASS
- static production build: PASS (`127` pages generated)
- static smoke: `94 URLs, PWA assets, 404 fallback, API target and deployment headers`: PASS

## Safety / non-actions

- No production database test or destructive migration was performed.
- No paid provider/GPU generation was triggered.
- No live-generation feature flag was enabled.
- No Cloudflare or DNS change was made.
- No external financial balance, legal certification, device acceptance, voice-rights evidence, or realtime capacity evidence was fabricated.
- Hunyuan security approval remains unchanged and fail-closed.

## CI follow-up hardening
- Owner Arabic coverage was completed for the new External Activation page; the repository Arabic coverage gate reports 1009 translatable UI strings with only the five approved technical tokens exempted.
- VIP Studio readiness badges preserve the template button accessible name through an explicit locale label, so browser automation and assistive technology still address capability buttons by their translated family name.

## Production deployment closeout — 2026-09-04

PR `#547` merged normally after all protected checks passed. The certified source/runtime merge is:

`53b5e086223111842eba59879e424f96bcb2062f`

### Pre-deploy rollback and database protection

Before recreating any Production service, every active execution/notification/backup/DR queue was verified empty. Rollback anchors were retained:

- Backend rollback tag: `aionex-aios-backend:rollback-pre-external-activation-20260904T073740Z` -> `sha256:4c25cb9e6e85123e437418113ebe7815525cbbda6d24f7f05e0143d8a9e9f274`
- Owner frontend rollback tag: `web-dashboard-frontend:rollback-pre-external-activation-20260904T073740Z` -> `sha256:587c62a14268b388d0503f1442ab0f4d6f559110d5e98bbd42fd8081183a7eb6`
- Pre-deploy PostgreSQL safety dump: `/opt/AIOS/.deployment-backups/external-activation-ui/20260904T073740Z/aionex-pre-external-activation.dump`
- Dump size: `19,186,585` bytes
- Dump SHA-256: `fc81981e60ebc4d2f6b6a63dd9522aebe18376bbaba19965aba8f9f336bcaf26`

### Backend and Super Owner deployment

The Backend and private Owner frontend were rebuilt from the merged source and deployed selectively:

- Backend image: `sha256:13ac3144c62e618b3b594835e3299b79f65de7adc3e6b1099039f3dcd1b0ab58`
- Owner frontend image: `sha256:0bd87d5e13cb9f6b9117ea1823da38d246e36383bf9ba70bcc93fd42fc99c232`
- Backend `/ready`: HTTP `200`, `{"status":"ready"}`
- Alembic: `20260825_0043 (head)`
- Owner `/owner/external-activation` renders from the deployed Owner image; `gabarot.vip-e.net` remains behind the expected Cloudflare Access HTTP `302` boundary
- All Backend-tagged workers were recreated only after a second zero-active-queue check; final `backend_tag_drift=0`
- Project workers remain `2/2` healthy and were not needlessly rebuilt because they use a separate project-worker image

### `ai.vip-e.net` user-interface publication

The user portal was published through the established shared-hosting route only. No DNS or Cloudflare Tunnel mutation occurred.

- Deployment route: `aionex-cpanel-ai-vip` -> `/home2/ipdom3m7/ai.vip-e.net/`
- Remote pre-deploy archive: `/home2/ipdom3m7/.aionex-deploy-backups/20260904T090542Z-external-activation-ui/ai-vip-before-external-activation.tar.gz`
- Archive size: `5,772,244` bytes
- Archive mode: `0600`
- Archive SHA-256: `7e93d6d624b7a64036598f40ebb5e1b3ded6356cfb521c80d5f8a54b29835216`
- `rsync --delete` preserved hosting-owned `cgi-bin/` and `.well-known/acme-challenge/`
- Package-owned local files: `322`
- Package-owned remote files: `322`
- Fixed-order SHA-256 manifest parity: `EXACT` (`322/322`)
- `.well-known/acme-challenge/` remains present
- `.well-known/assetlinks.json` remains present
- Published Studio client chunk: `/_next/static/chunks/app/[locale]/studio/page-5d8448dffd5cf780.js`
- Published/local chunk SHA-256: `e58b4db292363cd1921ca0f25b76f0425b97505f9de7109a51b5aa53645bc371`
- The live chunk contains both `readyBadge` and `externalGateBadge` governed UI paths

Live HTTP acceptance after publication:

- `https://ai.vip-e.net/`: `200`
- all locale roots `ar`, `en`, `fr`, `de`, `es`, `tr`: `200`
- all six localized `/studio/` routes: `200`
- `https://api.vip-e.net/ready`: `200`
- `https://gabarot.vip-e.net/`: expected Cloudflare Access `302`

### Final live ledger and resilience acceptance

The deployed read-only ledger reports the truthful current boundary state:

- registry gates: `16`
- current in-scope gates: `15`
- excluded current scope: `1`
- satisfied by live runtime evidence: `1`
- internally enforced with external evidence still pending: `6`
- blocked on genuine external facts/authority/infrastructure: `8`
- live payment evidence: `mada` and `stripe` are live-ready
- provider-funded-credit baseline: `0/3` for connected paid launch providers `deepseek`, `mistral`, and `openai`; no balances were fabricated
- direct Apple Pay, App Store publication, and Google Play publication remain excluded from the current closeout scope by Owner decision

A newer Platform backup produced during the deployment became the latest protected backup and therefore required a new matching restore validation before final acceptance:

- Platform backup: `c7679bea-2bf7-4b74-99dc-cc0e5b8764c3`
- Backup SHA-256: `0d3381ca931efe3c5d4a62c6f99439977df4c8be24121c3a2e7269b21e96ae40`
- Backup size: `18,968,546` bytes
- Matching restore-validation run: `a7ab63bf-4fdb-447d-92ac-9483fb311cb6`
- `validated=true`
- `three_d_snapshot_required=true`
- `three_d_snapshot_validated=true`
- 3D companion SHA-256: `4f972bd6abdcc1f3b049979da5c852cc519e5dd695856d7a82d338a4b683da22`
- scratch PostgreSQL databases after validation: `0`
- backup/3D restore scratch residue: `0`
- Operations Integration final completion: `100%`; Database, Redis, Backend, Runtime Components, Operations and Backup & Restore all report `healthy / 100`

Final runtime sweep after all publication and restore work:

- Production running containers: `30`
- bad containers: `0`
- Backend image drift: `0`
- Project workers: `2/2 healthy`
- active Design Image/Video/Speech/Transcript/Dubbing/Music/Song/Notification delivery executions: `0`
- active Project/3D/Backup/DR work: `0`
- failed systemd units: `0`
- UFW: active
- Fail2ban: active
- audit/test/non-running container residue: `0`
- audit/test network residue: `0`
- root filesystem usage at acceptance: `39%`

No paid provider/GPU generation, live-generation flag activation, Cloudflare/DNS change, fabricated balance, fabricated legal approval, or generic external-gate bypass was used during this deployment.
