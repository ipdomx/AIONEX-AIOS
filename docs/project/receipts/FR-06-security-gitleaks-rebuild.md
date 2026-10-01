# FR-06 — Gitleaks Go dependency rebuild (source and isolated image only)

Parent source: PR793 / 958cfbcf5ff62ecd836c53361b458eeeece5fef0.
This segment does not deploy any worker, retry the observer operator, change a
workflow, activate memory controls, or close FR-06.

## Exact build provenance

The upstream latest-release API still identifies Gitleaks 8.30.1. Its release
binary in the existing scanner image contains Go 1.24.11 and older x/crypto and
x/text, contributing 33 HIGH/CRITICAL finding instances in the retained scan.
Rather than relabel the existing binary, rebuild the same upstream source commit
83d9cd684c87d95d656c1458ef04895a7f1cbd8e using Go 1.27.1 and corrected module locks.

The Go archive is checked against the official go.dev SHA256. The source archive
is pinned by commit URL and recorded SHA256 from that official GitHub download;
no independent upstream archive signature is claimed. Go module sums and the
public checksum database remain enabled. No resolver bypass or forced downgrade.
The module changes are x/crypto 0.55.0, x/text 0.41.0, x/sync 0.22.0 and x/sys
0.47.0; the latter modules satisfy x/crypto's actual requirements. The initial
x/text 0.39 request was rejected and retained, not forced past the resolver.

The executable reports **8.30.1+aios.1**, an explicitly local rebuild. No detection
rule, allowlist, severity, report handler or upstream Go source is changed.
234 upstream code/rule/template/license/document files match before and after
the checked build. The binary retains build metadata identifying linked versions.
Its SHA256 is pinned in both the build lock and final installer:
7c8b599cead7b3c8cd4a55aac3a3c1238814f59d08a88b4078b1a18afa100f5b.

## Acceptance

- 32 new Python build-lock/archive/source-integrity contracts pass.
- All upstream Go tests pass: 275 test/subtest PASS events in seven packages,
  zero failed/skipped test events. This is not a race-detector run.
- A second independent extraction/build path using the committed build helper
  produced the exact same binary SHA256 and passed the same Go suite. Counts
  are repeated acceptance, not 550 independent tests.
- Both builds/tests run in unprivileged, capability-dropped, read-only containers
  with network disabled after public dependencies were downloaded. No host Go
  installation, private repository, token or production data is used.
- The initial test attempt lacked Git and dereferenced one upstream symlink.
  Its failures are retained. The final laboratory uses an extracted public Debian
  Git package read-only and preserves the original symlink, without changing or
  skipping upstream tests. Git is only a test/build prerequisite here.
- The final scanner child executes the real application argument builder and
  finding normalizer: a newly generated synthetic secret is detected, the safe
  control is not, ZIP detection works, invalid configuration is rejected, and
  tested reports redact the synthetic value. There are no real target scans.
- Ruff and Mypy pass for the two scripts. Full Root-suite results and exact
  source reconciliation are recorded in runtime acceptance, not inferred.

## Remaining security gate

The full unsuppressed image scan reports **263 HIGH/CRITICAL instances**, down
from 296: 145 OS and 118 other Go-binary instances remain. Gitleaks and Python
have zero HIGH/CRITICAL findings in that scan. No ignored IDs, excluded binaries,
severity changes, or ignore-unfixed relaxation. These counts are inventory
findings, not proof of reachability, exploitation, or a distinct-CVE count.

The narrow child replaces only Gitleaks and adds explicit provenance/license and
its verifier; it is not a complete clean rebuild of all source Dockerfile stages.
The source Dockerfile adds a dedicated hash-pinned Gitleaks build/test stage and
verifies the resulting binary before runtime installation; it must not download
the older release binary over that result. No .github/workflows file is changed.
The full image remains **NOT deployable** until OS and other Go findings and full
source-build/rollout gates are resolved.

Runtime evidence:
`docs/project/runtime/fr06-security-gitleaks-20260929T2300/`

FR-07 remains complete. The accepted Backend and two Telegram deployments remain
intact. The other 22 Python containers, observer operator block, remaining
C5D/C5E/C6 and production image rollout are not closed by this work.
