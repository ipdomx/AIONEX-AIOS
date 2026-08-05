# Phase 26 — Mobile and Telegram Delivery Readiness

## Status

Phase 26 prepares the already-built Android, iOS, PWA, and Telegram surfaces for controlled delivery while keeping paid publishing and external credentials outside the repository.

## Android

- Native Android project: `mobile/android`
- Package ID: `net.vipe.aionex`
- Minimum SDK: 27
- Target / compile SDK: 36
- Release outputs: signed APK and AAB
- Signing key and passwords remain outside Git under the operator-controlled configuration directory.
- The application bundles the verified VIP Frontend static export and serves it through an internal HTTPS asset origin.
- Static `_next` asset paths are rewritten to Android AssetManager-safe paths.
- External HTTPS links leave the embedded WebView; the local application origin is path-contained.
- Release lint, minification, resource shrinking, signature verification, installation, cold launch, and device smoke testing passed.

Retained operator artifacts:

- `/root/.config/aionex/releases/AIONEX-AIOS-Android-v1.0.0.apk`
- `/root/.config/aionex/releases/AIONEX-AIOS-Android-v1.0.0.aab`
- `/root/.config/aionex/releases/AIONEX-AIOS-Android-v1.0.0.sha256`

Google Play publication is intentionally not performed automatically because it requires an external developer account and an explicit commercial decision.

## iOS

- XcodeGen project definition: `mobile/ios/project.yml`
- SwiftUI application source: `mobile/ios/AIONEXAIOS`
- HTTPS-only portal navigation with allowlisted AIONEX hosts
- Offline fallback page
- Associated-domain entitlement template
- App icon catalogue
- Static source validation script: `scripts/mobile/validate_ios_source.py`

The source is ready for generation and signing on macOS. An IPA cannot be truthfully built or uploaded from the current Linux server because Apple signing and App Store tooling require Xcode/macOS and an Apple developer identity.

## PWA

The VIP Frontend is now installable as a progressive web application:

- complete Web App Manifest;
- PNG icons for Android and Apple devices;
- service-worker registration;
- offline fallback;
- safe cache policy that excludes API requests;
- static-hosting headers for the manifest, service worker, and association files;
- Android Digital Asset Links template;
- Apple App Site Association template.

VIP Frontend release version: `1.4.0`.

## Telegram

A production-shaped optional Telegram polling worker was added:

- token loaded exclusively from an external regular file;
- root-owned mode `0600` secret validation at the host boundary;
- private-chat-only command processing;
- explicit Telegram user allowlist;
- bounded long polling and message length;
- duplicate update protection through Telegram offsets;
- safe `/status`, `/projects`, `/executions`, and `/help` commands;
- no token, prompt, provider secret, or raw internal exception logging;
- Compose profile `telegram` remains disabled unless the operator installs a token file and enables it explicitly.

Expected operator secret path:

`/root/.config/aionex/telegram/bot-token`

No Telegram token existed during Phase 26, so no bot API request was sent and no fake deployment claim was made.

## Validation evidence

- Phase 26 mobile / Telegram contracts: `26 passed`.
- Telegram worker backend tests: `6 passed`.
- CI root contract boundary including Phase 26: `14 passed`.
- VIP Frontend `verify:static`: passed.
- Static smoke test: `69 URLs` plus PWA assets.
- Android release build: passed.
- Android APK signature scheme v2: verified.
- Android install and cold launch on the connected test device: passed.
- iOS source validation: passed.
- Both production Compose definitions: valid.

## Security and production boundary

- No mobile signing secret, Telegram token, API key, or store credential is committed.
- Telegram remains disabled without an external token.
- App Store and Google Play publication remain explicit external actions.
- No production database migration was required by Phase 26.
- Existing production services were not replaced or restarted for this source-readiness work.

## Remaining external actions

1. Distribute the signed APK for private Android beta testing.
2. Publish the PWA release to the existing `ai.vip-e.net` static host when a deployment channel is connected.
3. Create a Telegram bot and install its token externally before enabling the optional profile.
4. Build and sign iOS on macOS when Apple developer access is available.
