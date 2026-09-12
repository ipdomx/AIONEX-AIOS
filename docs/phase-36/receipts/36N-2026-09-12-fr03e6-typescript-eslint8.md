# Phase 36N receipt — FR-03E6 compatible typescript-eslint 8 pair

Date: 2026-09-12

The obsolete Dependabot proposal upgraded only `@typescript-eslint/eslint-plugin`, leaving the parser on major 7. FR-03E6 upgrades both plugin and parser to 8.70.0 as one compatibility unit and adds a repository contract forbidding mixed major versions.

Local acceptance before protected PR: npm audit zero vulnerabilities; Owner Arabic 1079 strings PASS; API contracts and TypeScript PASS; Next lint PASS; exact CI Prettier scope PASS; Next production build PASS. Merge/deployment are not claimed by this source receipt.
