# Phase 27 — Owner-Controlled VIP Portal and Pricing

## Status

Phase 27 adds the control layer required before product acceptance testing can begin. It does **not** declare AIONEX AIOS commercially ready. The website, provider catalogue, full user journey, video-generation workflows, mobile releases, and marketing launch remain subject to owner testing and approval.

The public VIP frontend remains a static, inexpensive hosting shell, while its presentation and commercial catalogue are loaded from the protected AIOS backend. After the new shell is uploaded once, routine content, design, branding, and pricing changes no longer require rebuilding or uploading another static archive.

## Super Owner control centre

The private Owner Dashboard now includes `/owner/portal` with draft, validation, publication, and rollback controls for:

- website name, short wordmark, suffix, tagline, logo, icon, and favicon;
- primary, secondary, status, page, surface, text, and muted colours;
- heading, body, and Arabic font families;
- owner-uploaded WOFF2 font files;
- background image, position, opacity, grid, glow, radius, width, spacing, logo size, and button style;
- public navigation labels, destinations, ordering, visibility, audience, and external links;
- all existing public and authenticated portal pages;
- page sections, ordering, visibility, images, feature cards, steps, statistics, FAQ, rich text, logo clouds, and calls to action;
- translation overrides for every client-side interface key in Arabic, English, French, German, Spanish, and Turkish;
- SEO title, description, image, keywords, and indexing policy per page;
- announcement bar content, severity, destination, visibility, and dismissal behaviour;
- support, sales, telephone, WhatsApp, address, and social links;
- footer text, columns, links, translations, visibility, and ordering;
- asset library upload, selection, reuse, and protected deletion;
- complete validated JSON editing for advanced fields;
- publication history and rollback.

Arbitrary JavaScript, executable HTML, unrestricted CSS, embedded credentials, and unsafe URLs are deliberately not accepted. Full owner control is implemented through validated product fields and design tokens rather than code injection.

## Pricing and subscription catalogue

A localized `/pricing` route is included in the VIP shell. The Super Owner controls:

- plan name, description, badge, ordering, visibility, and featured status;
- monthly, yearly, or custom subscription periods;
- duration in months;
- price, comparison price, and currency;
- plan features, limits, and entitlement identifiers;
- call-to-action label and destination;
- checkout provider and public checkout reference;
- pricing FAQ and tax note.

Only the free plan is enabled by default at zero cost. Professional and Business plans are present but disabled, and no paid price is invented. They become public only after the owner defines and approves the commercial terms and payment integration.

## Durable publication model

The existing `owner_control_records` table stores:

- one editable draft;
- one published configuration;
- versioned publication history;
- asset metadata.

Publishing is explicit. Saving a draft never changes the public website. Every publication, rollback, asset upload, and asset deletion produces an audit event. Published responses use ETags and bounded public caching.

## Asset boundary

Portal assets are stored outside Git in the production Docker volume mounted at:

`/var/lib/aionex/portal-assets`

Supported formats:

- PNG;
- JPEG;
- WebP;
- ICO;
- sanitized SVG;
- WOFF2.

The backend verifies size, type, path containment, SVG elements and attributes, references, and publication usage. A referenced asset cannot be deleted. Asset URLs are served from `https://api.vip-e.net` with immutable caching, MIME protection, a restrictive content security policy, and no directory disclosure.

## Public shell behaviour

VIP Frontend v1.5.0:

- fetches the published owner configuration from `/api/v1/portal/published`;
- applies design tokens without exposing the private Owner Dashboard;
- applies translated text overrides to the live interface;
- resolves localized navigation safely;
- renders controlled home and About page sections;
- renders the controlled pricing catalogue;
- exposes configured contact and social details;
- applies controlled footer and announcement content;
- updates browser title, description, favicon, and indexing instructions;
- keeps secure fallbacks when the configuration API is temporarily unavailable;
- never caches API responses in the service worker.

## Security boundary

The public channel exposes only:

- `GET /api/v1/portal/published`;
- `GET /api/v1/portal/assets/{asset_id}`.

All draft, asset-management, publication, reset, and rollback actions require the Super Owner role on the private control channel.

The configuration validator rejects:

- scripts and executable event attributes;
- `javascript:`, `vbscript:`, HTML data URLs, and unsafe path escapes;
- secret-bearing field names;
- common private-key and provider-token patterns;
- unsupported nesting and oversized content;
- invalid pricing, currencies, periods, colours, fonts, localization, and duplicate identifiers.

## Validation evidence

Completed validation before merge:

- isolated backend suite: `266 passed`, `1 skipped`;
- portal CMS tests: `5 passed`;
- Phase 22D through Phase 27 controlled boundary: `80 passed`;
- release and web contract boundary: `13 passed`;
- VIP Frontend v1.5.0 integrity, TypeScript, ESLint, static build, and smoke validation: passed;
- generated static pages: `73`;
- static smoke URLs: `76`;
- Owner Dashboard TypeScript, Owner lint, Prettier, and production build: passed;
- both production Compose definitions: valid;
- backend and Owner Dashboard Docker images: built successfully.

## Production and acceptance boundary

Phase 27 does not make the product ready for stores or marketing. After merge:

1. deploy the backend, private Owner Dashboard, Nginx allowlist, and durable asset volume;
2. verify the public configuration and private control endpoints;
3. create the VIP Frontend v1.5.0 static package;
4. upload that shell once to the existing `ai.vip-e.net` document root;
5. test publication from the Owner Dashboard;
6. begin the complete owner-led website acceptance plan;
7. connect and test each provider and paid service;
8. execute real projects, including advertising-video production;
9. approve the product only after the full user and owner experience passes.

## Merge and production deployment evidence

Phase 27 owner-controlled portal implementation was merged through PR `#188`.

- feature commit: `52bff4cb5ee6fc9eb90131055118393eb9db1dcf`;
- Nginx validation fix: `5538b5199b520161a12297fc3c9b6240e7ae8836`;
- merge commit: `0d1122d6a96b39b81b5f26c6d5834663f857e2ad`;
- GitHub checks: `9/9` successful, including Backend Tests, CodeQL, Dependency Security, Frontend Build, Production Docker Build, and Nginx Docker DNS Validation.

Production deployment completed on the existing single server without adding another server or changing the database schema.

Observed production evidence:

- public configuration endpoint: `200`;
- initial publication version: `1`;
- controlled pages represented: `11`;
- catalogue plans represented: `3`;
- enabled paid plans: `0`;
- unauthenticated private Owner API request: `401`;
- private Owner portal page through the internal origin: `200`;
- durable records: `draft` and `published`;
- asset volume permissions: mode `0750`, owner `aionex:aionex`;
- Alembic head remained `20260805_0006`;
- backend, frontend, Nginx, PostgreSQL, Redis, backup worker, and project worker remained healthy;
- Cloudflare Access continued protecting the private Owner hostname.

A validated pre-deployment PostgreSQL archive was retained outside Git at:

`/root/.config/aionex/backups/phase27-pre-portal-deploy-20260805T165531Z.dump`

## VIP Frontend v1.5.0 release

The one-time owner-controlled static shell was published as GitHub release:

`vip-frontend-v1.5.0`

Artifact:

`AIONEX-AIOS-vip-frontend-v1.5.0-owner-controlled-static-2026-08-05.zip`

- size: `1,863,973` bytes;
- SHA-256: `c6cc5d07e3b0f8e52ffabf6fd5a418e7e9833bb0479b61101048f8ee0d451b00`;
- ZIP entries: `198`;
- contains `.htaccess`, `.well-known/assetlinks.json`, PWA files, six locales, pricing routes, and no source maps;
- contains no private key, provider token, database credential, or Owner session.

The current shared-hosting document root remains unchanged until the owner uploads and extracts v1.5.0. This is the final routine static-shell upload required for this control architecture. After that upload, portal presentation and pricing updates are published from `/owner/portal`.

This deployment completes the portal-control prerequisite only. Full website acceptance, provider integration, video-generation tests, commercial plan approval, mobile-store publication, and marketing approval remain open.
