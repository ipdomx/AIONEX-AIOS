# Mobile delivery assets

- `android-builder/Dockerfile` pins the Linux Android SDK build environment.
- `well-known/assetlinks.json` contains the actual Android release certificate fingerprint for package `net.vipe.aionex`.
- `well-known/apple-app-site-association.example` is intentionally a template until an Apple Developer Team ID exists. It must not be published with the placeholder.

The Android declaration is also shipped from `vip-frontend/public/.well-known/assetlinks.json` so verified App Links become active when the v1.4.0 portal package is deployed to `ai.vip-e.net`.

## iOS Universal Links activation

The internal activation path is complete and fail-closed. Once the real Apple Developer Team ID is available, generate the production AASA document with:

```bash
python3 scripts/mobile/generate_apple_association.py \
  --team-id "$AIOS_APPLE_TEAM_ID" \
  --bundle-id net.vipe.aionex \
  --output vip-frontend/public/.well-known/apple-app-site-association
```

The generator rejects placeholders and invalid Team IDs. Do not publish an AASA document until the real signing Team ID is supplied and the signed iOS artifact uses the same bundle ID.
