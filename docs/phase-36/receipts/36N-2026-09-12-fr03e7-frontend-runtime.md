# Phase 36N receipt — FR-03E7 frontend runtime compatible group

Date: 2026-09-12

The post-Tailwind-4 runtime group contains only PostCSS 8.5.28, PostHog JS 1.428.8 and React Hook Form 7.87.0. Autoprefixer remains removed. PostCSS is updated in both direct dependencies and npm overrides to preserve a single enforced version.

Local acceptance on top of the FR-03E6 candidate: npm audit zero vulnerabilities; Owner Arabic 1079 strings PASS; API contracts and TypeScript PASS; Next lint PASS; exact CI Prettier scope PASS; Next production build PASS. This receipt does not claim protected merge or deployment.
