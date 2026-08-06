# Phase 29C — Identity, Tenancy, Access, and Accounts Completion

## Status

Phase 29C closes the non-provider identity and account surface for AIONEX AIOS. It replaces the remaining placeholder administration pages, persists workspace and team assignments, implements password recovery and TOTP multi-factor authentication, exposes account-session control, and retains the existing passkey, verified-phone, social-identity, role, permission, suspension, and authentication-generation protections.

Models and AI providers are not changed by this batch and remain reserved for Phase 29J.

## Durable schema

Alembic revision `20260806_0007` adds:

- persisted optional workspace assignment and last-active timestamp for users;
- organization-scoped teams with optional workspace scope;
- unique team memberships with lead/member authority;
- single-use, hashed, expiring password-reset records;
- encrypted user TOTP secrets and keyed recovery-code hashes.

The migration is additive. It does not rewrite existing users, roles, organizations, workspaces, sessions, passkeys, or external identities. Existing users remain valid with a null workspace assignment until explicitly assigned.

## Tenant and authority boundaries

- Normal owners and managers can only read and mutate their own organization.
- Workspace assignments are rejected when the workspace belongs to another organization.
- Team membership is rejected when the user belongs to another organization.
- Team routes conceal foreign-tenant records with a not-found result.
- Super Owner assignment and wildcard permission mutation remain protected.
- Suspended users, roles, and organizations invalidate refresh sessions and authentication generations.
- Workspaces with active projects or assigned users cannot be deleted.
- Every team mutation produces a durable audit event.

## Account recovery

Password recovery now:

- returns the same public response whether or not an account exists;
- rate-limits by normalized email and request address through Redis;
- generates a high-entropy token and stores only its SHA-256 hash;
- invalidates prior unused recovery tokens;
- expires tokens after a bounded configured period;
- delivers through the configured SMTP channel without logging the raw token;
- treats an unavailable SMTP channel truthfully as an undelivered request;
- allows one successful use only;
- rejects reuse, expiry, and the current password;
- increments `auth_version`, revokes every active refresh session, and audits completion.

The user portal includes localized Forgot Password and Reset Password pages for Arabic, English, French, German, Spanish, and Turkish. These pages are excluded from search indexing.

## Multi-factor authentication

Password sign-in supports a second TOTP/recovery-code step:

- setup secrets are encrypted at rest with a key derived from the deployment secret;
- eight recovery codes are shown once and stored only as keyed hashes;
- setup must be confirmed with a valid time-based code;
- password login returns a five-minute signed MFA challenge instead of access tokens;
- the challenge is bound to the user authentication generation;
- Redis makes each challenge one-time and prevents replay;
- a recovery code is consumed after use;
- disabling MFA requires both the current password and a valid TOTP or recovery code;
- disabling MFA increments the authentication generation and revokes sessions.

Passkey authentication remains available as a separate phishing-resistant credential path. Verified Firebase phone and configured social identity paths retain their existing identity-linking and channel-boundary contracts.

## Account sessions and settings

The account profile now exposes:

- current MFA status and remaining recovery-code count;
- passkey count;
- durable refresh-session history with address, user agent, creation, expiry, and revocation state;
- revocation of a selected session;
- existing all-session revocation after password and status changes;
- profile, avatar, password, locale, timezone, theme, and notification preferences.

Successful login and refresh activity updates the persisted user last-active timestamp.

## Administration UI

The previous Users mock array and the Organizations, Teams, Roles, and Permissions placeholders are removed. The protected dashboard now uses relational APIs to:

- list, search, create, update, suspend, restore, and delete users;
- persist and clear workspace assignments;
- list and create organizations and govern their active state;
- create, update, delete, and inspect teams;
- add, promote, demote, and remove team members;
- create and delete organization roles;
- inspect the permission catalogue and update role authority.

## Verification

The Phase 29C isolated acceptance uses disposable PostgreSQL and Redis services. Evidence includes:

- all Alembic revisions from the initial schema through `20260806_0007` applied from an empty database;
- focused identity, recovery, MFA, passkey, RBAC, and database-guard tests;
- complete Backend test suite: `286 passed, 1 skipped`;
- public portal TypeScript, ESLint, locale integrity, and production build;
- Owner dashboard TypeScript, Arabic coverage, ESLint, formatting, and production build;
- no use of the production database by pytest;
- no provider or model activation;
- no secret, reset token, MFA secret, recovery code, or authorization header committed to Git or returned by administrative APIs.

Production activation requires a database backup, `alembic upgrade head`, rebuilding only the affected Backend, Owner Frontend, and internal Portal services, followed by a temporary-tenant live acceptance and cleanup.

## Super Owner identity completion

The private Owner dashboard participates in the same MFA contract as the public account portal. Password login can return an MFA challenge, the private login gate accepts a TOTP or recovery code before storing any session, and the Owner settings page manages MFA enrollment, recovery codes, disable-and-revoke, session history, and individual session revocation.

Super Owner team creation accepts an explicit active organization and validates any selected workspace against that organization. Organization owners and managers cannot select or mutate a foreign organization.
