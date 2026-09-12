# Phase 36N receipt — FR-03E5 unused react-window removal

Date: 2026-09-12

This source receipt records the isolated FR-03E5 dependency decision. The tracked Frontend source has no consumer of `react-window`; both `react-window` and the legacy `@types/react-window` declaration are removed rather than performing an unused major-version migration. A focused repository contract prevents accidental reintroduction without reviewed usage.

Local acceptance before protected PR: focused contract 2/2 PASS; npm audit reported zero vulnerabilities; Owner Arabic coverage 1079 strings PASS; API contracts and TypeScript PASS; ESLint PASS; the exact CI formatting scope PASS; Next production build PASS. This receipt does not claim merge or deployment; those remain runtime journal facts.
