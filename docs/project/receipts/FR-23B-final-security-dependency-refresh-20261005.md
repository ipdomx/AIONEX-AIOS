# FR-23B — final security dependency refresh candidate (2026-10-05)

Status: **candidate; protected CI and independent binary reachability still required**
Base protected main: `46eb80c8b7474d26f1cc9a2c8718aabd4d842391`

## Scope

This candidate updates only dependency evidence required by the final security audit. It does not change production configuration, Cloudflare, providers, customer data, secrets, payment scope, or deferred scope.

Patchable open advisory paths are refreshed to their published fixed floors:

- frontend transitive `brace-expansion`: 5.x -> 5.0.12 and nested 1.x -> 1.1.21;
- Semgrep security environment `PyJWT[crypto]`: 2.14.0 -> 2.15.0;
- Gitleaks module graph: `rardecode/v2` -> 2.2.0 and `ulikunitz/xz` -> 0.5.15;
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
- Go module verification: PASS for Gitleaks, Syft, Grype and Trivy using pinned-or-newer compatible toolchains.
- No production deployment or restart occurred from this candidate.

## Acceptance still required

Before merge/FR-23 closure:

1. run the full pinned security-tools build from this exact candidate;
2. feed all four `go version -m` binary module outputs to `scripts/security/final_audit_reachability.py` and require PASS;
3. run protected repository CI including Security Baseline, CodeQL, Dependency Security, container/SBOM vulnerability gate and production build;
4. rescan Dependabot after merge and classify only the truly residual unpatched/non-runtime findings with evidence;
5. keep FR-23 exit semantics honest: every in-scope finding is either remediated or supported by a documented decision; no claim of absolute security.
