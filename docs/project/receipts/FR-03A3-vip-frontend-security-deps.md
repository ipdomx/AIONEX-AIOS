# FR-03A3 — vip-frontend dependency security update

- Security alerts discovered after Dependabot completed initial inventory: 13 open on main at observation time.
- Nine alerts belong to the intentionally vulnerable security-acceptance fixture and are not production dependencies.
- Four alerts belong to `vip-frontend/package-lock.json`: two Critical for Next.js, one High for sharp, one High development alert for js-yaml.
- Candidate upgrades Next.js and eslint-config-next to 15.5.24, forces transitive sharp to 0.35.4 via npm override, and resolves js-yaml to 4.3.2.
- `npm audit` after candidate install reports 0 vulnerabilities.
- `npm run verify:static` passed: integrity, type-check, lint, static build (139 pages) and static smoke (94 URLs).
- No hosting publish, application restart, provider request, Cloudflare change, or MCP change in this candidate.
