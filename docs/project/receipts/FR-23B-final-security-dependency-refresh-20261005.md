# FR-23B — final security dependency refresh candidate (2026-10-05)

Status: **candidate; exact local binary build/reachability PASS; protected CI still required**
Base protected main: `46eb80c8b7474d26f1cc9a2c8718aabd4d842391`

## Scope

This candidate updates only dependency evidence required by the final security audit. It does not change production configuration, Cloudflare, providers, customer data, secrets, payment scope, or deferred scope.

Patchable open advisory paths are refreshed to their published fixed floors:

- frontend transitive `brace-expansion`: 5.x -> 5.0.12 and nested 1.x -> 1.1.21;
- frontend runtime transitive `source-map-js`: 1.2.1 -> 1.2.2 after the exact-head dependency audit exposed GHSA-68fv-2mgg-jv7q;
- Semgrep security environment `PyJWT[crypto]`: 2.14.0 -> 2.15.0;
- Gitleaks module graph: `rardecode/v2` -> 2.2.0 and `ulikunitz/xz` -> 0.5.15; `mholt/archives` -> 0.1.5 is included because 0.1.2 is API-incompatible with rardecode/v2 2.2.0;
- Syft module graph: `containerd/v2` -> 2.3.6 and OpenTelemetry SDK family -> 1.45.0;
- Grype module graph: `containerd/v2` -> 2.3.6 and OpenTelemetry SDK family -> 1.45.0;
- Trivy module graph: `containerd/v2` -> 2.3.6 and the linked OpenTelemetry trace/SDK family -> 1.45.0.

The Go module floors require Go 1.26.8 or newer. This is compatible with the tracked pinned builders: Trivy already pins Go 1.26.8, while Syft/Grype/Gitleaks pin Go 1.27.1.

## Explicit residual findings

`github.com/docker/docker` remains `v28.5.2+incompatible` in the Trivy source module graph. The Go module proxy currently exposes no release newer than 28.5.2 for this module path, and repository Dependabot currently reports no published patched version for HIGH alerts #48/#50. Therefore this candidate **does not dismiss, close, suppress, or mislabel those alerts**. The existing FR-23 binary reachability contract must prove the legacy Docker module is not linked in the produced Trivy/Grype binaries, and the alerts remain documented residual source-level findings until an upstream module release or independently supported remediation exists.

Frontend `npm audit` also reports five HIGH findings in the lint-only `eslint-config-next` dependency chain. They are development tooling and are not shipped in the production Next.js runtime image. The available automated fix is a semver-major configuration change, so it is not applied blindly during final release closure. This remains a documented development-tooling residual unless a compatible upgrade is separately validated.

## Local candidate validation completed before publication

- `git diff --check`: PASS.
- `npm update brace-expansion --package-lock-only --ignore-scripts`: completed; both vulnerable brace-expansion lines moved to fixed floors.
- `npm ci --ignore-scripts --dry-run`: PASS.
- `npm audit --omit=dev`: PASS with 0 vulnerabilities after `source-map-js` 1.2.2 refresh.
- Go module verification: PASS for Gitleaks, Syft, Grype and Trivy using pinned-or-newer compatible toolchains.
- No production deployment or restart occurred from this candidate.

## Exact local post-repair validation

The dependency-refresh repair was rebuilt from this exact candidate in isolated, non-production containers after the initial protected CI exposed stale lock/binary pins and the Gitleaks `rardecode/v2` compatibility break.

- Gitleaks: rebuilt with `mholt/archives` 0.1.5 + `rardecode/v2` 2.2.0; 275 upstream tests PASS; binary SHA-256 `efc12ca6e29d2a8a3cf39f5693ff7c447093e61ed6f35c52356b6911e2b6ecbd`.
- Syft: 736 selected upstream tests PASS; binary SHA-256 `3b323bb5f8a59778ae004dc83ef6badadbe7d24d9931f3b41d3c4f4859d9108e`.
- Grype: 2407 selected upstream tests plus 8 completion regressions PASS; legacy `github.com/docker/docker` absent from the module graph/binary; binary SHA-256 `2ba1610b27fa2478f5eb0a00df4a4c1f8f4fbd690934d8cae1aa8f3fa0943846`.
- Trivy: 175 selected upstream tests PASS; all targeted OpenTelemetry modules, including `otlpmetricgrpc`, are at 1.45.0; binary SHA-256 `cf393282a6cf02605112e6886f466cb3c335826dff8172271de3b04441ab8b4d`.
- FR-23 binary/module reachability harness: PASS across Gitleaks, Syft, Grype and Trivy; the legacy Docker module is not linked in Trivy or Grype.
- Security build/lock/reachability contract tests: 187 PASS.
- No production container, provider, customer data, Cloudflare route or secret was changed by these isolated validation builds.

## Protected acceptance still required

Before merge/FR-23 closure:

1. run protected repository CI on the repaired exact head, including Security Baseline, CodeQL, Dependency Security, container/SBOM vulnerability gate and production build;
2. rescan Dependabot after merge and classify only the truly residual unpatched/non-runtime findings with evidence;
3. keep FR-23 exit semantics honest: every in-scope finding is either remediated or supported by a documented decision; no claim of absolute security.
