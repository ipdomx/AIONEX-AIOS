# AIONEX AIOS VIP Frontend

Production-ready Next.js user portal for the existing AIONEX AIOS platform.
It is the single public registration and user sign-in surface; the privileged
control plane remains a separate, access-protected deployment.

## What is included

- Home, About, Contact, Login, Registration, Dashboard, Profile, Projects,
  Privacy, Terms, 404, robots and sitemap routes.
- Complete Arabic, English, French, German, Spanish and Turkish interfaces.
- RTL/LTR layout, responsive navigation, dark/light themes and reduced-motion
  support.
- Real email login, token refresh and logout against the current FastAPI routes.
- Owner-controlled free registration that reads the live public policy before
  submission.
- Real Firebase mobile verification using only the browser-safe configuration
  returned by the backend.
- Real Google, Apple, Facebook, X and Instagram OAuth/OIDC through Firebase,
  exchanged server-side for first-party AIOS access and refresh tokens. New
  users can carry a one-use verified social identity into the owner-governed
  registration form without exposing provider tokens.
- Device-bound WebAuthn passkey sign-in, enrollment, listing and revocation.
- Real profile image, password, workspaces, project list, project creation and
  free-tier usage integration.
- A live user dashboard assembled only from authenticated project and quota
  responses; no seeded metrics or demonstration accounts.
- Private authenticated support requests delivered to authorized platform
  recipients.
- Security headers, same-origin backend proxy, standalone Next.js output,
  multi-stage Docker image and a static export for File Manager hosting.

## Integrated backend routes

The frontend calls the existing routes and the included authentication routes:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register/free`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/free-tier/public`
- `GET /api/v1/auth/firebase/phone/public`
- `GET /api/v1/auth/firebase/phone/readiness`
- `GET /api/v1/auth/firebase/social/public`
- `POST /api/v1/auth/firebase/social/session`
- `POST /api/v1/auth/firebase/social/registration/prepare`
- `GET /api/v1/auth/passkeys/public`
- `GET /api/v1/auth/passkeys`
- `POST /api/v1/auth/passkeys/registration/options`
- `POST /api/v1/auth/passkeys/registration/verify`
- `POST /api/v1/auth/passkeys/authentication/options`
- `POST /api/v1/auth/passkeys/authentication/verify`
- `DELETE /api/v1/auth/passkeys/{passkey_id}`
- `GET /api/v1/auth/free-tier`
- `GET|PATCH /api/v1/settings`
- `POST /api/v1/settings/password`
- `POST /api/v1/support/requests`
- `GET /api/v1/workspaces`
- `GET|POST /api/v1/projects`

Provider secrets remain exclusively in Firebase and the backend deployment.
The frontend reads only browser-safe Firebase configuration from AIOS and does
not contain provider secrets or fixed authorization URLs.

Super Owner accounts are rejected at the public gateway and in the browser
session guard. Privileged sign-in is served only by the separate control-plane
listener protected with Cloudflare Access; its hostname is not linked or
embedded in this portal.

## Environment and validation

```bash
cp .env.example .env.local
npm ci
npm run verify
npm start
```

The browser uses `/api/v1`. Next.js proxies that path to
`AIOS_BACKEND_ORIGIN`, whose production default matches the domain in the
repository deployment profile. Inside the existing Docker network, set
`AIOS_BACKEND_ORIGIN=http://backend:8000`.

## Docker

```bash
docker build -t aionex-aios-vip-frontend:1.2.0 .
docker run --rm -p 3000:3000 --env-file .env.local aionex-aios-vip-frontend:1.2.0
```

## File Manager hosting

The shared-hosting package is built without a Node.js runtime:

```bash
npm ci
npm run verify:static
```

Upload the **contents** of `out/` to the document root for `ai.vip-e.net`. The
generated package calls `https://api.vip-e.net/api/v1` directly and includes an
Apache/LiteSpeed `.htaccess` with the production security and cache headers.
