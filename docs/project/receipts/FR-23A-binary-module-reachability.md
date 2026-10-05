# FR-23A — binary/module reachability regression harness

Status: **source-only preparation; FR-23 remains OPEN**
Base origin/main: 109492b3ddfa0838e4330934679011e14bd668c3

## Purpose

This FR-23-owned harness converts the go version -m evidence already emitted by
the pinned Trivy, Grype, Syft and Gitleaks build scripts into a fail-closed,
machine-checkable reachability result. It is deliberately narrower than SCA
closure: a module absent from a built binary is useful mitigation/reachability
evidence, but **does not dismiss or close a source-level dependency advisory**.

In particular, Dependabot HIGH alerts **#48 and #50 remain OPEN** until the
shared Trivy/source dependency finding is independently remediated and rescanned
by its actual owner/coordinator. No VEX assertion is created by this work.

## Owned files

- scripts/security/final_audit_reachability.py
- tests/test_fr23_binary_module_reachability.py
- tests/fixtures/fr23_binary_module_policy.json
- this receipt

No shared dependency manifest, workflow, Docker package source, production
service, provider, secret, MCP setting or live database is changed.

## Evidence contract

The harness accepts one complete binary-modules.txt file per security tool.
Those files are produced from go version -m by the existing pinned builders:

- web-dashboard/backend/scripts/build_trivy.py
- web-dashboard/backend/scripts/build_grype.py
- web-dashboard/backend/scripts/build_syft.py
- web-dashboard/backend/scripts/build_gitleaks.py

Evidence is rejected if it lacks normal path/build metadata, contains fewer than
the configured minimum number of linked dependencies, omits one of the required
tools, or uses a replacement for a targeted module. This prevents a
short/truncated file from turning "not observed" into a false PASS.

The committed policy enforces reachability-only checks for:

- legacy github.com/docker/docker absent from Trivy and Grype binaries;
- linked containerd/v2 at v2.3.6+, or absent;
- linked OpenTelemetry module family at v1.45.0+, or absent;
- linked Gitleaks rardecode/v2 at v2.2.0+, or absent;
- linked Gitleaks xz at v0.5.15+, or absent.

Every rule carries closure_effect=none. The policy loader itself refuses a
fixture that enables Dependabot closure or stops preserving alerts 48/50.

## Current-main inventory at this base

Read-only inspection of the tracked security-tool manifests at this base still
shows source dependency versions that require owner/coordinator remediation:

- Trivy: containerd/v2 v2.3.3, OpenTelemetry v1.44.0, and indirect
  github.com/docker/docker v28.5.2+incompatible.
- Grype: containerd/v2 v2.3.5, OpenTelemetry v1.44.0; its builder separately
  rejects legacy github.com/docker/docker in the module graph and linked binary.
- Syft: containerd/v2 v2.3.5, OpenTelemetry v1.44.0.
- Gitleaks: rardecode/v2 v2.1.0, xz v0.5.12.

The existing isolated security acceptance lab also contains source/static and
web security coverage (including Semgrep-backed source findings, secret/source
checks, ZAP, Nuclei, Nikto, testssl and behavioral authz/CSRF probes), while
Trivy/Grype are pre-warmed for vulnerability detection. This receipt does not
rerun that lab and does not claim DAST acceptance.

## Final-audit boundary

FR-06 and FR-21 are still not accepted, so FR-23 live/final closure and the
dependent isolated DAST acceptance remain gated. When those prerequisites and
shared dependency remediation are accepted, the coordinator can cold-build the
candidate security-tool binaries, feed their four binary-modules.txt outputs to
this harness, run the full isolated security lab/SAST/SCA/SBOM/DAST matrix, and
record residual risk against the exact integrated candidate.

Host Docker maintenance remains a separate controlled maintenance gate. This
work does not change package sources, restart Docker, or infer host closure from
binary reachability.

## Run-specific verification

The tracked receipt defines the acceptance contract only. Exact pytest/static
results, commit and publication outcome belong to the worker run receipt and
must be recorded truthfully after execution; they are not pre-claimed here.
