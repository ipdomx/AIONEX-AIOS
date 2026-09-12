# FR-03E3 — remove unused direct Zustand dependency

Base: `f859f919bd5123c39471ddd9a31197647cc78cfd`

The dashboard does not import Zustand directly. React Flow is the only frontend consumer and already declares its own `zustand ^4.4.1` dependency. The direct dashboard pin `zustand ^4.5.0` therefore adds no application capability and would cause an unnecessary independent major migration to Zustand 5.

This candidate removes only the direct dashboard dependency. React Flow continues to resolve `zustand 4.5.7` transitively, so React Flow runtime behavior and dependency ownership are unchanged.

Acceptance:
- direct Zustand declaration removed from `package.json` and root lock dependencies;
- React Flow retains `zustand ^4.4.1`, resolving to 4.5.7 transitively;
- focused removal contract: 2/2 PASS;
- npm audit: 0 vulnerabilities;
- Owner Arabic coverage: 1079 translatable strings, 5 approved technical tokens;
- API contracts + TypeScript: PASS;
- ESLint: PASS;
- Prettier: PASS;
- Next production build: PASS, 92/92 static pages;
- AIOS core suite: 970/970 PASS.

No production deployment is performed by this source-only subpart. Protected GitHub checks remain mandatory before merge.
