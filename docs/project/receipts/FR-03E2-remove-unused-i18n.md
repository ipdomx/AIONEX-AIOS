# FR-03E2 — remove unused i18n frontend dependencies

Base: `3f18f2c8ded219991de3e734618cb529c949cd4b`

The Dependabot proposal to upgrade i18next from 23.x to 26.x was reviewed instead of merged blindly. Repository usage review found no tracked frontend imports of `i18next`, `react-i18next`, `i18next-resources-to-backend`, `useTranslation`, `Trans`, or `i18next.init`. `npm ls` showed the three packages were direct-only i18n tooling and no other project package depended on them.

The safer change removes all three unused dependencies instead of introducing a major i18n migration with no runtime consumer.

Acceptance:
- `npm ls i18next react-i18next i18next-resources-to-backend --all`: empty.
- `npm audit --omit=dev`: 0 vulnerabilities.
- Owner Arabic coverage: 1079 translatable strings / 5 approved technical tokens.
- API contracts and TypeScript: PASS.
- Owner ESLint and Prettier checks: PASS.
- Next production build: PASS, 92 static pages.
- Removal contract: 2/2 PASS.
- AIOS core suite: 968/968 PASS.

No frontend deployment is performed in this subpart. Protected GitHub checks remain mandatory before merge.
