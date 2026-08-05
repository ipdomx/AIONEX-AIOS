# AIONEX AIOS Android

Native Android shell for the production user portal.

## Runtime

- package: `net.vipe.aionex`;
- minimum Android: API 27;
- target/compile SDK: API 36;
- primary content: `https://ai.vip-e.net/ar/`;
- bundled fallback: local offline page and static assets;
- clear-text traffic: disabled;
- arbitrary file/content access: disabled;
- external links: opened by the device browser.

## Reproducible release build

The Linux server builds with the pinned Docker SDK image:

```bash
scripts/mobile/build_android.sh
```

The signing key and passwords live only under `/root/.config/aionex/mobile/` and are excluded from Git. Release outputs are copied to `/root/.config/aionex/releases/` with SHA-256 checksums.

Generated Gradle state, copied portal assets, APK/AAB outputs, and signing files are ignored by Git.
