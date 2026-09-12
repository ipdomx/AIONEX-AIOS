# 36N / FR-03E2 — remove unused i18n frontend dependencies

- Base: `3f18f2c8ded219991de3e734618cb529c949cd4b`
- Removed unused direct frontend dependencies: `i18next`, `react-i18next`, `i18next-resources-to-backend`.
- No tracked frontend source imports/usages found.
- Frontend acceptance: npm audit 0, Arabic/API/type/lint/format PASS, production build 92 pages.
- Core acceptance: 968/968 PASS.
- No production deployment in this source-only subpart.
