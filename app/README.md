# AIONEX AIOS app (Flutter)

One Dart codebase for the Android app, the iPhone app and the signed-in web
workspace. Plan and status: `docs/project/COMPLETION-ROADMAP.md`, section
"التطبيق الحقيقي (Flutter)" (tasks N-01 … N-11).

## Layout

| Path | What it is |
|---|---|
| `lib/src/core/api/` | `ApiClient` (Dio): bearer token on phones, httpOnly cookies on the web, one shared refresh on 401, `ApiException` for every failure |
| `lib/src/core/auth/` | Session storage (Keychain / Keystore on phones), sign-in, MFA, restore, sign-out |
| `lib/src/core/router/` | go_router; `redirectFor` decides splash / sign-in / workspace |
| `lib/src/core/locale/` | The six website languages; Arabic is right-to-left |
| `lib/src/core/theme/` | "Obsidian & Crimson" identity, IBM Plex Sans Arabic bundled |
| `lib/src/features/` | Screens |
| `lib/l10n/*.arb` | **Generated** from `vip-frontend/src/messages` + `l10n_extra/` |

## Translations

The website's message files are the single source of every sentence, so a
wording fix there reaches the app too:

```bash
python3 app/tool/sync_messages.py          # regenerate lib/l10n/*.arb
python3 app/tool/sync_messages.py --check  # CI fails when they are stale
```

App-only strings go in `l10n_extra/<lang>.json` (keys get the `app_` prefix).

## Build and test

Flutter 3.44.0 / Dart 3.12.0, the same pinned image in CI and on the server:

```bash
flutter pub get --enforce-lockfile
flutter analyze --fatal-infos
flutter test
flutter build web --release --no-web-resources-cdn
flutter build apk --release --split-per-abi
```

`--dart-define=AIONEX_API_BASE=https://…/api/v1` changes the backend
(HTTPS only; plain HTTP is accepted solely for localhost in debug builds).

`test/live/` checks the contract with the real backend and is skipped unless
`AIONEX_LIVE_EMAIL` / `AIONEX_LIVE_PASSWORD` name a dedicated test account.

## Security rules

- No secret ever ships in the app: every value in it is public by design.
- Phones keep only the refresh token, in the Keychain (this device only) or
  the Android Keystore; the access token lives in memory.
- The web build never holds tokens in Dart; the browser's httpOnly cookies do.
- The Super Owner cannot sign in here; the owner console stays separate.
- Signing keys (`*.jks`, `key.properties`, provisioning profiles) never enter git.
