# FR-03E1 — remove unused date-fns dependency

Base: `bc73c717564e65cb6673c4df102ac29058371059`.

The Dependabot proposal to upgrade `date-fns` from 3.6.0 to 4.4.0 was reviewed instead of merged blindly. Repository source search found no `date-fns` imports in the tracked frontend source or scripts, and `npm explain date-fns` showed the package was required only as a direct root dependency. The safer change is therefore to remove the unused dependency rather than introduce a major version with no application use.

Acceptance:
- `npm ci`: PASS, 0 vulnerabilities.
- Owner Arabic coverage: PASS, 1079 translatable UI strings and 5 approved technical tokens.
- Owner infrastructure API contracts: PASS.
- TypeScript check: PASS.
- Owner dashboard ESLint: PASS with no warnings/errors.
- Prettier check: PASS.
- Next.js production build: PASS, 92 static pages.
- Dependency/source contract: 2/2 PASS.
- AIOS core suite: 966/966 PASS.

No production frontend deployment is performed in this subpart. Protected GitHub checks remain mandatory before merge.
