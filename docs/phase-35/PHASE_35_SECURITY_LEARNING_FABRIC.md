# Phase 35 — Autonomous Security & Learning Fabric

Status: implemented behind Owner-controlled entitlements and security-target admission.

## Purpose

Phase 35 adds a durable application-security control plane to AIONEX AIOS. The platform records new project/test/security experience, but no user statement, model output, scan observation, or generated detector becomes trusted knowledge automatically. Experience is quarantined, provenance is retained, rules are validated against positive and negative corpus cases, and only the Super Owner can promote verified security knowledge.

## Ten completed implementation batches

1. **Adaptive intelligence foundation** — evidence ledger integration, trust scoring, provenance, contradiction penalties, quarantine and anti-poisoning promotion gates.
2. **Security control plane** — Super Owner entitlements (`standard`, `advanced`, `elite`, `autonomous`), target inventory, policy, quotas, audit events and fail-closed admission.
3. **SAST/SCA/secrets/SBOM** — built-in source checks plus isolated adapters for Semgrep, Bandit, Trivy, OSV-Scanner, Grype, TruffleHog, Gitleaks, Syft and optional enterprise analyzers.
4. **Web/TLS/attack surface** — TLS/certificate checks, security headers, CSP/cookies, Nuclei, Katana, ProjectDiscovery httpx, testssl.sh, Nmap and Nikto capability integration; OWASP ZAP is an optional API-key-protected internal service.
5. **API/identity validation** — passive OpenAPI authentication/authorization contract analysis, per-user entitlements, durable scan jobs, rate/concurrency limits and worker leases.
6. **Deep validation lab** — advanced/elite scenarios require a distinct Super Owner-registered security clone; authorization matrices never invent expected policy decisions.
7. **Infrastructure/container/mobile** — Docker/Compose hardening analysis, Android manifest and iOS plist checks, container and mobile tool registry, bounded isolated workers.
8. **Security Genome / Rule Forge** — confirmed findings may create quarantined detector candidates; corpus validation and trust thresholds precede promotion to verified AIOS knowledge.
9. **Autonomous remediation** — confirmed managed-project findings can create isolated remediation copies only when Owner policy and entitlement allow it; patch evidence, regression checks and a security retest are mandatory; production is never auto-modified or auto-merged.
10. **Security release gate and Owner UI** — Owner dashboard controls grants, managed targets, security clones, evidence triage, rules and release gates. Release decisions depend on completed scan evidence plus configured backup/restore assurance.

## Target authorization boundary

- A managed AIONEX deployment is bound to a durable project ID. An entitled user may register only a project they can access and only under Super Owner-approved deployment-domain suffixes; the backend verifies public DNS before admission. The Super Owner retains global policy, entitlement, clone, evidence and release authority.
- External targets require proof via an HTTP file challenge before scanning.
- DNS is re-resolved at admission/execution time; a changed address set invalidates the previous authorization and requires re-verification.
- Loopback, private, link-local and other non-global targets are rejected to prevent SSRF/internal-network scanning.
- A user cannot convert production into a security clone by changing a request field. Only the Super Owner can register a separate clone origin linked to an already verified managed target.
- Advanced/Elite intrusive validation is admitted only for that isolated clone.

## Learning boundary

`Observation -> Candidate Knowledge -> Verification -> Corpus/Sandbox -> Trust Score -> Owner Promotion`

Security scan completion is recorded as experience, not truth. The same evidence-gated fabric now receives structured experience from project creation, governed project execution success/failure, explicit user knowledge submission, AI-agent execution outcomes, security scans and remediation retests. Raw provider prompts/output and raw exceptions are deliberately excluded from the adaptive event path. Confirmed findings, false positives, successful remediations and failed rules all contribute evidence while preserving provenance and tenant isolation. Promoted Security Genome rules are stored in the existing verified Knowledge/Learning subsystem.

The public VIP portal exposes the Security Lab only after backend entitlement checks. It lets an entitled account bind its own managed AIONEX project to an Owner-approved public deployment domain, choose only profiles granted by the Owner, queue/cancel scans, inspect durable findings, and request remediation only when the autonomous entitlement and Owner policy both permit it. Security-clone creation, rule promotion, finding confirmation and release-gate authority remain Super Owner-only.

## Tool runtime

Security engines run in `aionex-aios-security-tools:local`, separate from the public API/backend image. Release binaries are version-pinned and verified against upstream checksum assets where available; the Nuclei template snapshot and testssl source snapshot are hash-pinned. The worker is non-root, capability-dropped, source mounts are read-only and scratch storage is bounded. Optional ZAP is internal-network only, has no host port, requires a secret API key and is enabled through a Compose profile.

The runtime capability heartbeat is durable, so the UI reports what the scanner worker actually has rather than claiming unavailable tools are active.

## Release rules

A clean scanner output alone cannot approve release. Confirmed policy-blocking findings block. Unverified severe observations require Owner review. Required TLS/header checks, recent backup evidence and recent restore/DR evidence must be present when enabled in Owner policy. Remediation is `Verified Fixed` only after regression evidence passes and the original finding fingerprint is absent from the completed retest.

## Acceptance evidence

The Phase 35 candidate is accepted only when the complete root regression, isolated backend regression/migrations, Ruff, mypy, Owner dashboard Arabic/type/lint/build gates, six-locale VIP static verification, Compose validation, security-tool image validation and the pinned ZAP daemon smoke all pass. A passive ZAP end-to-end check is performed only against an isolated local fixture network; it does not touch production. GitHub protected gates must pass on the pull request and again on merged `main` before the phase is considered closed.
