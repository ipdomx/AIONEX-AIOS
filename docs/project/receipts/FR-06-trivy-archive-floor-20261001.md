# FR-06: pinned Trivy archive dependency security correction

Status: isolated, locally verified source candidate. Not merged, installed or deployed.
Base: `41b42aea51650e0838f8d11e34e43cbdac21e729` (PR #835).
Worktree: `/opt/AIOS-worktrees/fr06-trivy-refresh-20261001T222440Z-d9496245`.
Evidence: `docs/project/runtime/trivy-refresh-lab/` inside this worktree.

## Exact change and boundaries

Upgrade only the selected `github.com/moby/go-archive` dependency from `v0.2.1`
to `v0.3.0`, authenticated by the Go checksum database. The resolved `go.mod`
delta is one dependency line; `go.sum` gains the two real v0.3.0 checksums.
Retained older checksum entries are not a selected dependency version.
Update both immutable module-file digests in the existing Trivy build lock.
Require exactly the reviewed archive version and refuse module replacement
rules before building, even if someone rehashes an old or redirected input.
No detector/parser/test assertion, linked-module floor, workflow, threshold,
production configuration, maintenance authority or provider operation changed.

Official advisory: https://github.com/moby/go-archive/security/advisories/GHSA-hfg8-hc9c-6c3h
Reviewed database: https://github.com/advisories/GHSA-hfg8-hc9c-6c3h
Both list v0.3.0 as patched; their affected-range wording differs, so no claim
is made about an intermediate version. The candidate pins v0.3.0 explicitly.

## Real reproduction and verification

`tests/security_labs/fr06_go_archive_refresh.go.txt` is a reproducible native
Go test fixture. It uses only newly owned temporary directories, synthetic
file contents and an actual nonroot process (UID 65534). There is no Docker
API, live application data, mount, service action or provider call.

- Old v0.2.1: three tests pass; the chained-link containment test FAILS because
  a synthetic file is written outside the extraction destination, still fully
  within the disposable test root.
- New v0.3.0: all four tests pass, with no skips. Normal files and valid
  contained relative links continue to work, while escape paths are refused.
- Selected upstream archive tests: seven test functions, ten test/subtest
  pass events, zero failures or skips in the final run. The earlier broader
  selection had two root-dependent skips and is retained, not counted passed.
- Source lock and existing Trivy build regressions: 61 passed.
- Actual `go mod verify`: exit 0. Actual module query selects v0.3.0 with the
  authenticated checksum and no `Replace` object.
- Seven previously selected Trivy test packages: 175 passing test/subtest
  events, zero failures or skips. This is NOT all upstream Trivy tests.

The full pinned Linux Trivy CLI was rebuilt as UID 1000 from the SHA-256
verified upstream archive using the already pinned Go 1.26.8 compiler. Existing
content-addressed build caches were reused; they were not claimed new or cold.
Upstream source/embedded payload fingerprints remain unchanged.
The resulting executable SHA-256 is exactly
`82e0a73a831efc894c1df0de6893eb653145570d2b186f395338628ba380345e`,
matching the pre-existing reviewed binary pin. Go build metadata confirms
neither `github.com/moby/go-archive` nor the legacy `github.com/docker/docker`
module is linked into this Linux CLI. That explains the identical executable;
this is still a valid correction to the source/test dependency graph. Do not
claim this rebuilt unchanged CLI upgrades the host Docker daemon.

## Remaining distinct risks

Dependabot #51 is not remotely closed merely by a local source change.
The legacy docker module is still selected in the source/test graph via
`aquasecurity/testdocker`, `trivy-checks` and `trivy-kubernetes`; alerts #48 and
#50 are not removed, suppressed or claimed fixed by this candidate.
A full image scan and fresh runtime acceptance were NOT performed here.

Separately, a read-only Docker version query at 2026-10-01T22:35:46Z reported
client/server 29.1.3. The official daemon advisories list versions below 29.5.1
as affected. Distribution backports have not been established, and no host
upgrade/restart or live vulnerability experiment was attempted.
References:
https://github.com/moby/moby/security/advisories/GHSA-rg2x-37c3-w2rh
https://github.com/moby/moby/security/advisories/GHSA-x86f-5xw2-fm2r
A separately controlled host upgrade requires the project's actual maintenance,
recovery and exclusive-executor conditions, not this library test result.

## Integration status

PR #835 itself is unchanged on 41b42aea, with all eleven mandatory app-bound
checks observed successful. No duplicate successor replaces it. The live source
remains 7779f740; missing shared ingress and unresolved scheduled effects are
not accepted by source tests. FR-06, C5D/C5E/C6 and the previous credential
incident remain open; FR-07 closure is preserved.

## Complete project root suite

The byte-matched owned source export ran as real UID65534 outside `/tmp`:
3923 tests, zero failures, zero errors, zero skipped; exit 0 at
2026-10-01T22:38:16.594812+00:00. The 61 focused source tests overlap this suite
and must not be added to that count. JUnit SHA-256:
`82a7d071f013a62aa7b8a4a4fc6460ae0af0550c435e7124728c80fc1b0c79eb`.
The export included 2689 byte-verified source files and excluded Git credentials,
all runtime evidence, and the prior incident file. The archive native regression
and Trivy Go suites above are independently retained with their narrower scope.
Protected GitHub CI has not run for this new local archive patch.
