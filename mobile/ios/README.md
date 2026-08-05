# AIONEX AIOS iOS

Linux-preparable iOS application source for the production user portal.

## Runtime

- bundle identifier: `net.vipe.aionex`;
- deployment target: iOS 17;
- UI: SwiftUI with a hardened `WKWebView`;
- primary content: `https://ai.vip-e.net/ar/`;
- bundled offline fallback;
- associated domain prepared for `applinks:ai.vip-e.net`;
- no insecure transport exceptions.

## Validation on Linux

```bash
python3 scripts/mobile/validate_ios_source.py
```

The validator checks the source layout, bundle identifier, HTTPS portal boundary, entitlement, complete icon catalogue, and absence of signing material.

## Build and distribution

A Mac with Xcode is required for compilation, simulator/device testing, archive signing, and TestFlight/App Store delivery. Generate the Xcode project with XcodeGen:

```bash
xcodegen generate --spec project.yml
```

Apple team IDs, certificates, provisioning profiles, and App Store Connect credentials must remain outside Git and will be configured only when an Apple Developer account and Mac build channel are available.
