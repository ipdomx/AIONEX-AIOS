# FR-06 — production build repair and Docker alerts #34/#36

Owner instruction (2026-09-30): FREEZE all new merges and deployments until
production build failure and both high alerts are repaired and verified. This
instruction supersedes the previous immediate-merge policy. This branch is a
repair candidate only. No main/source synchronization, service recreation,
maintenance transition, workflow edit, or previously blocked action is permitted
by this receipt. Existing open pull requests had no auto-merge requests.

## Reproduced production-build failure

main804 / 632839c3 run 36687245763 failed Production Docker Build at "Build core
production images". Both frontend Dockerfiles demanded libcrypto3/libssl3
3.5.8-r0, which the signed Alpine repository had replaced with 3.5.9-r0. The
original command was reproduced with exit 4 against the same pinned Node base.

Both Dockerfiles now upgrade the signed stable repository packages and enforce
libcrypto3/libssl3 >=3.5.9-r0, matching resolved versions, and a fail-closed apk
version comparison. Resolved versions are recorded in tls-packages.txt. The
base-image digest, unprivileged runtime, removal of build-time npm/yarn, and APK
signature checks remain. The later redundant unrestricted upgrade was removed
so the recorded versions are the final resolved TLS packages.

An actual Docker build of the identical runtime package block passes. The
resulting container runs as 1001 with no capabilities and verifies both packages
at 3.5.9-r0, absence of npm/yarn, and Node crypto operation. This isolated stage
result is not by itself a certificate for the complete production build.
Initial test-harness failures (apk info output assumptions and root without DAC
permissions to remove node-owned installer files) are retained; neither is
hidden or interpreted as a production incident.

## Targeted high alerts, removed through code migration

GitHub Dependabot #34 / CVE-2026-41567 / GHSA-x86f-5xw2-fm2r and #36 /
CVE-2026-42306 / GHSA-rg2x-37c3-w2rh concern github.com/docker/docker <=28.5.2.
The advisory has no patched version under that legacy module path. It is not
sufficient to change inventory metadata or suppress the advisory.

The only Grype imports retaining that monolithic module were Docker-backed shell
completion and a test-only homedir helper. Reviewed local source replacements
migrate completion to already-resolved github.com/moby/moby/client v0.6.0 and
API v1.56.0, with no change to scanner/matcher/parser behavior. The test uses
os.UserHomeDir rather than importing the legacy Docker module. New real Go
regressions exercise prefix/multiple-tag results, the non-dangling filter,
API-version negotiation, empty results, denied/malformed replies, and shell
fallback when a daemon is absent, using a synthetic loopback server only.

The dependency graph is resolved with Go tools. The old module is absent from
go.mod, go.sum, go list -m all, and compiled build information. No replacement
module masquerades under the old name; Docker-backed completion remains enabled.
Source input hashes and exact before/after fingerprints for all three migration
files are pinned. The builder refuses source drift and checks the complete
migration before writing any file. Version is explicitly local 0.119.0+aios.2.

Two real builds, including the final repository helper, produced executable
49d40604b87e06f6de7cf17beaf7a2ac48b7617e6f01c88e2ce842d904001fa8.
The final build has 2,407 passing native upstream test/subtest events in nine
selected packages, plus 8 passing completion test/subtest events. Not a full
upstream-suite or race-detector claim. Original source differs only in the two
reviewed migration files and one new regression file, apart from resolved module
metadata; the vulnerability-matching rules remain unchanged.

The corrected immutable child image passes the installed native Grype verifier:
affected/fixed synthetic metadata, real application arguments/execution/result
normalization, failure thresholds, invalid checksum, missing DB and malformed
input. Its generated fixture DB is explicitly not the current public feed and
is never installed as the runtime feed. No production data, Docker daemon socket,
client secrets, or external scan targets are used.

## Independent full image scan and limits

The corrected child is sha256:4ce41a40f3a9f5a4ae26e7455d060baf7605974898faa156fa09a0dd8f583665.
An unsuppressed complete HIGH/CRITICAL scan with database update 2026-09-30T07:10Z
inventories 297 Grype package records including the modular Moby client/API. It
finds neither legacy Docker nor either targeted CVE; Grype HIGH/CRITICAL is zero.
The complete image STILL has 219 other HIGH/CRITICAL finding instances (147 OS,
72 other Go). These are not distinct-vulnerability/exploitability counts. No
ignored IDs, altered severity, missing-tool trick, or ignore-unfixed bypass.

The default-branch Dependabot alerts cannot be declared closed before the fixed
source is merged. They are not dismissed manually. Production images still have
their previous packages while the owner's deployment freeze remains in effect.
A full green CI build must be verified on the exact candidate commit before
calling the production-build regression repaired. This receipt records local
results; final CI status and source-suite counts are sealed in runtime evidence.

FR-07 remains complete; FR-06 and whole-image approval remain open. Previous
observer, Syft diagnostic/helper, workflow and C5E9 blocks remain unchanged.

Evidence: docs/project/runtime/fr06-production-build-high-fix-20260930T103539Z/.
