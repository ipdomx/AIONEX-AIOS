# FR-06 — Trivy source rebuild and native scanner acceptance

Status: isolated source/image work on top of PR810 (`340d577f`), NOT merged or
published. The owner's other-merge/deployment/live-source holds remain in force.
Main809 post-merge validation and the unchanged-head CodeQL rerun for PR810 were
separately observed successful; they do not authorize merging this branch.

## Corrected executable and preserved capabilities

The official Trivy 0.74.0 archive and checksum manifest matched the GitHub release
asset SHA256 values. The signature bundle was not independently verified. The
source archive is pinned to exact commit e1fd17a0ea4a8cf24bc4b4dd7e2cfbf4bb31b994;
its captured digest is not represented as an upstream signature.

The official executable itself still reported two HIGH gRPC findings. The local
build moves gRPC from 1.82.1 to 1.83.2; Go dependency resolution also updates the
three required GCP/SPIFFE indirect modules, explicitly retained in module-delta.
It does not rename or hide a vulnerable library and does not patch any upstream
scanner, parser, vulnerability matcher or rule. The local version is explicitly
0.74.0+aios.1, not an official upstream executable.

Trivy upstream still uses the experimental JSON v2 API. The first attempted Go
1.27.1 build failed because that release removed SkipFunc; Go's release notes
confirm that change. The supported Go 1.26.8 patch release was downloaded and
hash-verified, preserving upstream GOEXPERIMENT=jsonv2. No parser compatibility
shim, assertion removal or disabled security check was added to force Go1.27.
The first lab also exhausted its 1.5 GiB tmpfs compiler scratch; only the owned
lab scratch moved onto a bounded-duration, separately mounted directory. Host
/tmp, swap, production mounts and the 4 GiB Docker reserve were not altered.

The native build and separate final repository helper reproduced the same SHA256:
82e0a73a831efc894c1df0de6893eb653145570d2b186f395338628ba380345e.
The module files, toolchain, source and output are pinned. All 1,943 fingerprinted
upstream source/test/document files remain unchanged. The source Dockerfile runs
the builder and selected tests and installs its executable/license/provenance;
the existing installer now rejects another version instead of downloading an
older binary. No workflow file was modified.

## Native acceptance and limitations

- The selected seven-package upstream scope has 175 passing test/subtest events,
  zero failures or skips: Debian and library vulnerability detection, DB, report,
  dpkg and npm parsing, and secret analysis. Repeated builds repeat the same
  coverage. This is not the entire upstream suite, a race run, or acceptance of
  external daemon/registry integrations.
- The final immutable image executes the unchanged application's actual argument
  builder, subprocess adapter and finding normalizer with all three scanner modes
  enabled: vulnerabilities, misconfigurations and secrets. A single-advisory test
  database and synthetic Apache metadata give affected/fixed controls with exit
  thresholds 7 and 0. The fixture database is historical/synthetic, NOT a current
  public feed and is never installed as the runtime vulnerability database.
- The built-in Dockerfile DS-0002 root-user rule matches USER root and not the
  USER 1000 control. A custom synthetic marker exercises the secret pipeline;
  built-in rules are not disabled and their upstream tests remain in scope.
  Empty input, malformed SBOM, missing DB and incompatible DB schema are checked.
  Test source and fixture fingerprints remain unchanged.
- The initial synthetic Debian root omitted the required etc/debian_version file;
  the fixture was completed rather than accepting an empty result. A second
  assertion used an obsolete advisory spelling; actual JSON uses DS-0002. The
  exact semantic assertion and positive/negative controls were retained. One
  tool call timed out before native evidence could be retained; its container
  was verified absent before a new bounded execution. All failures are retained.
- Tests are unprivileged and network-disabled; no client data or production
  socket/service is exposed. A diagnostic update probe was blocked by that
  network restriction. The final verifier additionally disables version checks
  only in its own laboratory environment, without altering production defaults.
- Thirty-nine new source/lock/build contracts are included in the Root suite.
  Final complete Root counts and exact source hashes are in runtime acceptance.
  Ruff and Mypy results are recorded without relaxing rules or ignoring imports.

## Whole-image gate remains FAILED

Final image: sha256:e7fc5e13341a578f658692fd1ddea240ad06e601409bb05465360ce86718dcfe.
The independent complete scan explicitly inventories 377 Trivy packages,
Go 1.26.8 and corrected gRPC 1.83.2. Trivy contributes zero HIGH/CRITICAL findings.
The image still has 200 OTHER HIGH/CRITICAL finding instances:
144 OS and 56 other Go. Against the prior 216-instance PCRE2 image, the same
vulnerability-database update removes exactly 16 Trivy instances and adds none.
No ignored IDs, excluded tools, severity edits or ignore-unfixed weakening.
Counts are not distinct vulnerabilities or evidence of exploitation; this is
not an all-severity clean result or permission to deploy.

Image comparison preserves 518 pre-existing application files, both Python
environment trees, all OS package versions and 14 other native executable files.
Only Trivy plus explicit build provenance/license and the new verifier differ.
This narrow child is not a full clean-source build certificate for every stage.

All other merges/deployments/live-source synchronization remain frozen. Previous
observer, Syft diagnostic/helper, workflow and C5E9 blocks are not retried. FR07
remains complete; FR06, the remaining scanner-image findings and later runtime,
drain, host-state, memory and boot acceptance remain open.

Evidence: `docs/project/runtime/fr06-security-trivy-20260930T1235/`.

## CI cold-build correction (2026-09-30)

Candidate bd5a86dc's Production Docker Build, run 36719900374 / job
109902047586, FAILED in trivy-builder. Its retained completed-job log shows
Python's outer subprocess timeout expiring at 600 seconds while executing the
unchanged seven-package `go test` command. Grype was still building in parallel.
The log does not prove which compiler/test subprocess was active at timeout;
no native assertion failure or successful full CI acceptance is inferred.

The corrected build makes Trivy wait for the completed Grype build by copying
only Grype's build-provenance receipt into the Trivy builder stage. This is an
ordering dependency, not reuse of an unverified/prebuilt Trivy executable. No
workflow permission or file is changed. Trivy's Go test/build commands receive
a fixed 1,800-second outer budget for cold compilation; the actual Go package
test deadline remains 120 seconds, `-count=1`, all seven selected packages,
nonzero/failed/skipped-test rejection, source/module pins, jsonv2 and the expected
binary digest are unchanged. Download and module-validation budgets are unchanged.
A cold-compile budget is not a relaxation of runtime security or load-test SLOs.

Each cold command now emits a machine-readable timing/status receipt. On failure
it retains and prints only the last 16 KiB of the compiler/test log, with JSON
escaping and without the process environment. Exceptions and timeouts are still
raised and existing receipts are not overwritten. Contract tests include real
nonzero process exit, timeout propagation, bounded/control-escaped diagnostics,
symlink rejection for diagnostic reads, build ordering and unchanged test scope.

A separate isolated rebuild starts with an EMPTY Go build cache, two CPUs,
6 GiB memory, no network and the already hash-verified public module/archive
inputs. Its outcome, output digest and exact-source acceptance are recorded in
runtime evidence; the earlier warm-cache result is not relabeled a cold build.
CI must re-run on the corrected head before full build acceptance. The old
failed run remains historical evidence. Neither local acceptance nor the
200-finding child scan authorizes merge, production deployment or source sync.

Correction evidence: docs/project/runtime/fr06-security-trivy-20260930T1235/ci-build-investigation-20260930T1346/.
