# FR-06 — httpx toolchain rebuild and bounded native acceptance

Source base: merged PR794 at ecb9c030dda5c58426d2e13d2871399096309c82.
This is source and isolated-image work, not a production rollout or FR-06 closure.
PR793 and PR794 were merged only after all 12 checks passed on their exact heads.
Live source was fast-forwarded only to accepted main792 (40b50991) while the new
main workflows remained pending; no service recreation accompanied that sync.

## Rejected newer upstream binary

The official ProjectDiscovery httpx v1.12.0 ZIP and checksum manifest matched the
release API's SHA256 digests. Its actual executable embeds Go 1.26.0. A complete
binary-inventory scan reported 22 HIGH/CRITICAL instances. The first filesystem
scan returned success but inventoried ZERO artifacts, so that result was rejected
rather than interpreted as security acceptance. Its output is retained alongside
the actual rootfs/binary inventory. The official executable was NOT deployed.

## Accepted local source rebuild

The exact upstream commit 4b6a9a9d476f94a4f3a630f37051f5671ecfb1f8 is rebuilt with
hash-verified Go 1.27.1. The only upstream application-source edit is an explicitly
local version marker, v1.12.0+aios.1. Detection, HTTP parsing, auth, TLS, CPE and
other logic are unmodified. go.mod is unchanged; go.sum has 426 supplementary
checksum entries verified by the enabled Go checksum database. All original
checksum entries remain present. This is a local rebuild, not the official binary.

The repository builder includes fixed source/toolchain/module hashes, read-only
module selection, linked-module checks and the expected output binary SHA256.
Independent build executions, including the final repository helper, produced
6c1ce29485bed5b29e1f9e4291d5c0bbbb7c7294598dc3b8f1780925e2516507.
The source Dockerfile includes the build/test stage; the runtime installer checks
the prepared local binary and never overwrites it with the older release artifact.
No .github/workflows permission change is attempted.

## Test scope and limits

- 37 new source/build-lock contracts passed, covering identity/hash/file drift,
  symlinks, local-version marker integrity and build/runtime integration.
- 368 selected native upstream test/subtest events passed per successful build,
  with zero failed or skipped events within that selected scope. The scope is
  explicit: auth providers, HTTP utilities/input formats, common HTTP/TLS/parser
  tests except external TestDo, and named runner/CPE/port tests. External network,
  ASN/DNS integration and internal/pdcp suites are NOT claimed as executed. Tests
  ran in an unprivileged disposable container with network disabled. Repeated
  builds are repeated coverage, not independent cases to add together.
- The initial noexec tmpfs prevented any Go test executable from starting. Only
  the disposable test container's tmpfs was corrected; the failed run is retained.
  Host /tmp, swap and mount options were not changed.
- The final immutable child image executes the real application argument builder
  and execution adapter. Five loopback HTTP fixtures verify normal 200, redirects,
  404, 500 and gzip responses/title extraction. Invalid options are rejected.
  The application reports completed fingerprinting without fabricated findings.
  No real external target, client project, credential or provider was used.
- Ruff and Mypy pass for both new scripts. Full Root results and exact source
  fingerprints are in the runtime receipt; no prior Root run is substituted.

## Security and production gates remain open

The final image scan still FAILS: 255 HIGH/CRITICAL finding instances, comprising
147 OS and 108 other Go instances. Python, Gitleaks and rebuilt pd-httpx contribute
zero HIGH/CRITICAL instances; the binary must be present in the scan inventory.
The OS count grew by two relative to the previous dated baseline despite unchanged
OS packages. The totals must not be presented as a simple 263-minus-10 comparison
without acknowledging the changed scanner database. No exclusions or ignore-unfixed
weakening are used. This is not an all-severity zero-vulnerability statement or a
full clean-source scanner image rebuild/deployment certificate.

Runtime disk reserve was checked before image construction. The unpublished first
candidate was archived and its exact build-cache references removed before a smaller
single-payload-layer final candidate was created. Explicitly unused old test images
were also checksum-archived; data volumes and production containers were not removed.
Archive restore execution is NOT claimed. The final free-space observation remains
an independent gate: do not start further image builds below the 4 GiB reserve.

FR-07 remains complete. Observer-operator/workflow/C5E9 blocked operations were not
retried. Backend and the Telegram workers were not redeployed. The remaining Python
worker rollout, OS/Go image remediation, drain, host-state/memory and boot acceptance
remain open. Evidence: docs/project/runtime/fr06-security-httpx-20260930T0342/.

## Continuation — repair newly failing main dependency gate

The exact post-merge main794 run 36665391112 finished with a failed frontend
production-dependency audit. Backend tests and Production Docker Build succeeded;
the failure was NOT waived or rerun without a change. The published Moment
advisory GHSA-4p3w-j4w9-5jqw affects >=2.29.2,<2.31.0 and identifies 2.31.0 as
fixed. It concerns server-side lazy locale loading with attacker-influenced
non-string input; presence in this lockfile does not establish application
exploitability, and a browser-only exposure is not asserted.

Updated exactly one package-lock entry, Moment 2.30.1 -> 2.31.0, inside the
already permitted transitive dependency ranges. No other dependency or override
changed. npm production audit reproduced the moderate finding before the update
and returned zero known findings afterward. Published npm SHA512 integrity was
verified for both original and corrected packages.

The added Node regression suite exercises real packaged Moment code. Seventeen
cases cover crafted/non-string and string locale inputs, locale fallback, six
supported locale round-trips, leap dates, UTC offsets, normalization and prototype
names. Three cases fail on the old package, all seventeen pass on the corrected
one. Unsafe module resolution is intercepted before filesystem access; no outside
file is read and no network request is made. This verifies a guarded local
regression, not exploitation of production. The suite is included in the existing
frontend API-contract/type-check command; .github/workflows files stay unchanged.

Complete combined-source Root, frontend type/build and final audit receipts are
retained under resume-20260930T0524. They must be checked before source acceptance;
the prior httpx-only Root result is not substituted for these changed files.
Live frontend deployment is a separate pending gate; no live container is updated
by this source repair and main794 remains historically failed.
