# AIONEX AIOS — Core Production Release Candidate Acceptance — 2026-08-13

Status: **RC_GO**

The core AIONEX AIOS production platform completed a live Release Candidate acceptance against the deployed production stack. No new product feature, payment expansion, Azure quota workaround, or AWS quota workaround was introduced during this acceptance.

## Production baseline

- Production `main` was clean and synchronized with `origin/main` before acceptance.
- Public site `https://vip-e.net` returned HTTP 200.
- VIP portal `https://ai.vip-e.net` returned HTTP 200.
- Private Owner hostname remained behind Cloudflare Access and returned the expected redirect boundary.
- Backend, PostgreSQL, Redis, Nginx, Portal, Frontend, project worker, communications worker, backup worker, operations observer, security workers, Telegram worker, 3D worker, and private Ollama runtime were running; health-managed services were healthy.
- The live Production Runtime API reported `completion=100` with database, Redis, backend, runtime-components, and operations all `ready`.

## Tenant and public-channel lifecycle acceptance

A synthetic non-Super-Owner E2E identity was exercised through the public API boundary.

- Public authenticated identity endpoint: HTTP 200.
- Same non-Super-Owner identity against the private control channel: HTTP 403.
- Owner-only runtime surface through the public channel: HTTP 404.
- Workspace creation: HTTP 201.
- Project creation: HTTP 201.
- Provider-neutral project execution: HTTP 202, then durable completion at 100% progress with review stage and no execution error.
- Refresh flow: HTTP 200.
- Project and workspace cleanup: HTTP 200.
- Durable audit evidence included workspace creation, project creation, provider-neutral completion, project deletion, and workspace deletion.

The real free-tier boundary was separately validated with a temporary synthetic tenant and then removed completely:

- Free-tier status exposed a one-project limit.
- Free-account workspace mutation was denied with HTTP 403.
- First project creation succeeded with HTTP 201.
- Second project creation was denied at the free limit with HTTP 429.
- Billing/usage visibility returned HTTP 200.
- The synthetic free tenant and its temporary project were removed after acceptance.

## AI execution and routing acceptance

Live provider execution was used; no provider success was simulated.

- Core `AIRoutingLayer` selected Groq as the direct route and returned `RC_DIRECT_OK` with approximately 278 ms provider latency.
- A bounded acceptance harness forced the selected Groq route to fail without changing the durable provider record. The routing layer then failed over to the private Ollama runtime and returned `RC_FALLBACK_OK`; two routes were executed and the failed primary was recorded as failed.
- Durable AIOS Groq agent execution completed with `RC_DURABLE_GROQ_OK`, 64 tokens, and approximately 216 ms latency.
- Durable AIOS Ollama execution completed with `RC_DURABLE_OLLAMA_OK`, 52 tokens, and approximately 6.2 s latency on CPU.
- Temporary acceptance agents were deleted after execution; completed durable jobs and audit evidence remain available.
- AI job notifications were visible through the Owner notification surface.

Provider truth after acceptance:

- **13 connected:** Anthropic, Cohere, DeepSeek, Fireworks, Gemini, Groq, Hugging Face, Mistral, Ollama, OpenAI, OpenRouter, Together, xAI.
- **Configured external gates only:** Azure OpenAI and AWS Bedrock.
- Azure OpenAI and AWS Bedrock remain in `configured`, not `connected`, until their provider-side quotas permit a successful durable live job.

## RC defects found and fixed

Two core authorization/visibility defects were discovered by live acceptance and fixed in PR #301.

### Existing tenant built-in role permission drift

Tenant organizations created before later permissions were added to the platform catalogue could retain stale built-in role assignments. An existing tenant Owner therefore lacked newer notification/communication permissions.

The startup seed path now performs a narrow additive backfill only for existing non-deleted tenant roles whose names already match assignable built-in roles. It:

- does not create missing tenant roles;
- never creates a tenant Super Owner;
- does not remove tenant-defined permissions;
- does not resurrect deleted roles;
- is idempotent across backend restarts.

Production validation after deployment confirmed the legacy tenant Owner has 58 explicit permissions, including `notifications:read` and `communications:read`, with zero tenant Super Owner roles created. The live notifications endpoint returned HTTP 200 after the fix.

### Super Owner Security Audit scope

The Security Audit endpoint used by the Owner UI was tenant-scoped even for the Super Owner, hiding audit events from other organizations. The endpoint now applies no organization filter for the Super Owner while preserving strict tenant isolation for all other roles.

Production validation confirmed the Super Owner Security Audit endpoint can see the tenant RC audit event and tenant actors remain isolated to their own organization.

PR #301 merged as commit:

`2fe5d8c2bffae4b655b7c261f7cc85cdba18cf92`

## Backup and disaster-recovery acceptance

- Latest completed protected backup had a non-empty checksum and size `3,998,432` bytes.
- A real disaster-recovery test was queued through the Owner API.
- The backup worker completed the isolated restore validation.
- Final DR state: `completed`, `validated=true`, `dry_run=true`, with no restore error.
- No in-place production restore was performed.

## Post-RC Telegram hardening and user bot

A deliberate post-RC Telegram change was approved and completed after the original Core RC acceptance. The `RC_GO` decision remains unchanged.

### Protected Super Owner Telegram bot

The existing operations Telegram bot was converted into a protected Super Owner-only control surface and deployed in PR #306.

- Telegram access remains private-chat-only and restricted by the explicit owner allowlist.
- Allowlisting alone is not sufficient: the Super Owner must issue a short-lived second-factor challenge from the protected Owner surface and authenticate in Telegram.
- Owner challenge lifetime: 5 minutes.
- Authenticated owner session lifetime: 30 minutes.
- Five failed authentication attempts lock that Telegram identity for 15 minutes.
- `/logout` immediately revokes the active Telegram owner session.
- Owner sessions are bound to the current AIOS `auth_version`, so a security/session-generation change invalidates the Telegram session.
- The owner bot token remains outside Git in the operator-controlled root-only secret file and is copied into a private runtime path before privilege drop.
- Production owner Telegram worker remained healthy after the user-bot rollout.

PR #306 merged as commit:

`451781ce0d3dba7664a7347e22248e5837313f40`

### Public user Telegram bot

The older Phase 14 in-memory Telegram identity-linking design was not reused as an in-memory authority. Its one-time-link/revoke concept was upgraded into a durable production implementation and deployed in PR #307.

- Dedicated user bot and worker: `user-telegram-worker`, Compose profile `telegram-user`.
- Dedicated secret boundary: `/root/.config/aionex/telegram/user-bot-token`, root-owned mode `0600`; it is separate from the Super Owner bot token and is never committed, echoed, returned by APIs, or logged.
- The worker verified its live Telegram bot identity through Telegram and persisted only non-secret bot identity metadata.
- Account linking starts only from an already authenticated AIOS user session. The portal issues a 16-character high-entropy one-time challenge valid for 5 minutes.
- Only the challenge HMAC digest is stored durably; the plaintext challenge is never persisted.
- Linking is accepted only in a Telegram private chat and binds the Telegram identity and chat to the authenticated AIOS account.
- A Telegram identity cannot be linked to a second AIOS account, and an AIOS account cannot silently switch to another Telegram identity.
- The Super Owner is rejected from the public user bot and must use the protected Owner bot.
- Every user-bot command re-resolves the current database user, role permissions, `auth_version`, billing account, plan limits, and entitlements at execution time. Upgrade, downgrade, suspension, role changes, entitlement changes, or security-generation changes therefore take effect without trusting stale Telegram-side authority.
- A changed `auth_version` requires a fresh portal link. A suspended billing account pauses user-bot access.
- Current safe commands include account/role/plan visibility, usage, current capabilities, permitted projects, unread notifications, and explicit unlinking. Command visibility and execution are permission-aware rather than assuming Free, paid, and higher-tier users are equivalent.
- Telegram notification delivery now selects the correct bot token from durable endpoint metadata: Owner-scoped endpoints remain on the protected Owner bot, while verified user endpoints use the user bot.
- The VIP notifications surface includes the authenticated Telegram link/revoke flow and localized account-linking copy for all six supported portal languages.

Live and production validation completed for the user bot:

- User token host file validated as a regular root-owned `0600` file without reading or printing its contents.
- `user-telegram-worker` reached and maintained Docker `healthy` state with zero polling errors.
- Live Telegram `getMe`/polling connectivity completed through the worker without exposing the token.
- A temporary synthetic production tenant validated durable one-time linking, Free-plan permission behavior, `auth_version` invalidation, and cleanup; the synthetic records were removed after the test.
- Backend, Portal, communications worker, Owner Telegram worker, and user Telegram worker were rebuilt from merged `main` and were healthy after deployment.
- PR #307 passed Backend Tests, Core Owner/Release/Web contracts, Frontend/VIP/Owner builds, Browser E2E boundaries, CodeQL, dependency security, repository secret audit, SBOM/vulnerability gate, dynamic Docker DNS validation, and Production Docker Build before merge.

PR #307 merged as commit:

`5226633bbe50eaf822a0193852bf4167c3be678a`

### Public ingress hotfix

Post-deployment verification found that the new authenticated `/api/v1/telegram/*` routes were initially absent from the strict Nginx public API allowlist. The backend and worker were healthy, but the portal linking API correctly remained unreachable through the public boundary. This was treated as a release blocker rather than accepted as a partial deployment.

PR #308 added only the three required authenticated user routes to the public allowlist — `status`, `link-challenge`, and `link` — plus a regression ingress contract. All PR gates passed before merge. Because Nginx uses a file bind mount, the container was recreated after the merge so the new inode was mounted before final validation.

Final live ingress evidence:

- unauthenticated `GET /api/v1/telegram/status` through the public Nginx/API channel: HTTP `401` from the backend;
- an unlisted Telegram API path through the same public channel: HTTP `404`;
- Nginx configuration syntax: valid;
- Nginx, Backend, Portal, communications worker, Owner Telegram worker, and user Telegram worker: healthy.

PR #308 merged as commit:

`2d1d15dda123b3c3e260ddd69f3d6afb76de0162`

A real human-user Telegram account link remains appropriate as part of the controlled pilot; no claim is made that a human Telegram pilot was completed during this engineering closeout.

## Final production state

After the RC fix was deployed:

- Production Runtime: **100%**.
- Database: ready.
- Redis: ready.
- Backend: ready.
- Runtime components: ready.
- Operations: ready.
- Active queued/running AI jobs: 0.
- Active running AI agents: 0.
- Active DR runs: 0.
- Active RC projects/workspaces left behind: 0.
- Git working tree: clean.

All GitHub workflows on the RC fix merge commit completed successfully, including Final Validation, Security Baseline, Phase 34E Container Security, CodeQL, Browser E2E Boundaries, backend tests, frontend build, dependency security, SBOM/vulnerability gate, production Docker build, legacy PostgreSQL compatibility, and backup/restore round-trip validation.

## External gates excluded from Core RC

The following are not Core RC failures and remain explicit external activation work:

- Azure OpenAI provider quota approval and final durable live execution.
- AWS Bedrock inference quota approval and final durable live execution.
- Apple App Store and Google Play production account/credential activation before final mobile-store billing acceptance.
- Commercial paid-plan prices remain Owner-controlled and were intentionally not invented during this RC.

## Decision

**RC_GO** — the core AIONEX AIOS production foundation is ready for feature freeze and controlled pilot/launch-readiness activity. New feature work should remain frozen until external activation gates are completed or a deliberate post-RC change is approved. Any post-RC core change must carry a regression test and pass the full production gate set before deployment.
