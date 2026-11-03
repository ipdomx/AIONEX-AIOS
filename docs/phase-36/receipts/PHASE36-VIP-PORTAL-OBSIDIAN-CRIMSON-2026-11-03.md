# Phase 36 Reporting Receipt — VIP portal "Obsidian & Crimson" visual identity

- Receipt ID: PHASE36-VIP-PORTAL-OBSIDIAN-CRIMSON-2026-11-03
- Batch: cross-cutting visual identity (no capability maturity change)
- Date/time UTC: 2026-11-03
- Objective: Apply the owner-mandated black + red identity to the VIP portal (`vip-frontend/`).
- Phase 36-owned paths touched: `vip-frontend/src/components/pages/projects-client.tsx` and `studio-client.tsx`. Only colour utility classes changed (cyan/violet/electric → crimson/obsidian/zinc, red → rose). No behaviour, routes, API calls, data-testids or aria attributes changed.
- Backend: `PortalTheme` default colours, Arabic font and radius in `web-dashboard/backend/app/services/portal_cms.py`. No schema change and no migration.
- Security/privacy/cost: fonts are self-hosted through `next/font` at build time, so the CSP is unchanged and there are no new runtime third-party requests.
- Tests: source contracts that reference the VIP frontend pass locally. CI runs the VIP type, lint, static build and browser E2E checks.
- Rollback: revert the PR. There is no data change.
- External activation gates remaining: none.
