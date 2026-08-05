# Mobile delivery assets

- `android-builder/Dockerfile` pins the Linux Android SDK build environment.
- `well-known/assetlinks.json` contains the actual Android release certificate fingerprint for package `net.vipe.aionex`.
- `well-known/apple-app-site-association.example` is intentionally a template until an Apple Developer Team ID exists. It must not be published with the placeholder.

The Android declaration is also shipped from `vip-frontend/public/.well-known/assetlinks.json` so verified App Links become active when the v1.4.0 portal package is deployed to `ai.vip-e.net`.
