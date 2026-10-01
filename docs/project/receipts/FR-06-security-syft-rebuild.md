# FR-06 — Syft pinned-source rebuild and native inventory acceptance

This is an independent source/isolated-image segment, not a production rollout.
PR800 was merged at `1d24d13701a5c70c25377b67b5563522b40ac95b` only after all
15 candidate checks passed and its 103 retained evidence files were reverified.
The worktree was fast-forwarded onto that graph without changing source bytes;
production source synchronization remains gated by post-merge main acceptance.

## Real code/compiler change, not an inventory exclusion

The official Syft 1.52.0 release asset and checksum manifest both matched their
GitHub release digests. The binary inventory contains 275 packages, including
Go 1.26.3, and reports 11 HIGH/CRITICAL instances. That official binary was NOT
accepted or deployed merely because it was newer.

The exact upstream commit `02ba369d13b4248395b20a504eca94b0cab564d8` is rebuilt
with the official SHA256-verified Go 1.27.1 toolchain. The executable has the
explicit local version `1.52.0+aios.1`. No upstream Go source or cataloger/parser
logic is edited. go.mod is unchanged; go.sum retains all original entries and
adds 732 checksums obtained with the Go checksum database enabled. The module
lock, source archive, toolchain and resulting executable hashes are pinned.

The native test/build and independent repository helper produced the same
SHA256 `4251a6a8e77e0a332815c6977a3f62fe9a391d21985caea733a9aee8f8a216be`.
The source Dockerfile includes this builder and tests. Its runtime installer
rejects an unexpected version rather than downloading the older official binary.
The original licenses and build provenance are carried into the image.

## Tests and honest scope boundaries

- 45 new source-lock/archive/build-contract cases passed locally. Full Root
  results and exact source fingerprints are retained in the runtime manifest;
  no earlier suite is substituted for the final source.
- The accepted upstream subset has 736 passing test/subtest events with no
  failures/skips *inside that selected subset*. Repeated builds repeat the same
  coverage. This is NOT the entire Syft upstream suite and no race run is claimed.
- Six named image-fixture/repository tests are excluded explicitly because the
  lab neither exposes a Docker daemon nor contains a Git checkout. The first,
  broader attempt produced 13 failing events for these missing prerequisites;
  those logs remain, and that attempt is not claimed successful. No upstream
  test assertion or production guard was edited to turn those failures green.
- Three upstream absolute-symlink fixtures under the unselected fileresolver
  suite are recorded but never materialized. The generic extractor still rejects
  them. The Syft-specific extractor verifies the pinned input and exact omitted
  fixture identities; additional absolute links, path escapes, special files,
  changed fixture identities, duplicates and existing output are rejected.
- The final image actually runs the application's argument builder and execution
  adapter. Four synthetic packages across Python, JavaScript and Debian are
  inventoried with exact names/versions and package URLs, alongside Debian OS
  and file entries. CycloneDX, Syft JSON and SPDX conversion preserve inventory.
  Empty input, invalid output format and malformed SBOM handling are tested.
  Inventory is not fabricated into vulnerability findings. Files remain unchanged.
- Initial functional fixtures omitted an npm lock/root version and treated all
  CycloneDX entries as versioned libraries. The actual output exposed that test
  assumption. The fixture and assertions now explicitly verify packages, OS and
  file components separately; no application parser was changed.
- All functional tests use synthetic files in a disposable, unprivileged,
  network-disabled container. No client project, provider, database, credential
  or host Docker socket is passed into the test.
- Ruff and Mypy pass for both scripts. Formatting-only changes were AST-matched,
  and the final helper and verifier were run again using their final bytes.

## Full image gate is still FAILED

The final narrow child has 238 HIGH/CRITICAL instances: 147 OS and 91 other Go.
This is down from 255 on the same scanner database update timestamp. Syft's
contribution is now zero rather than 17; the scan explicitly inventories its
275 packages and corrected compiler/modules. Python, Gitleaks and pd-httpx also
remain free of HIGH/CRITICAL findings in this scan. No ignored IDs, excluded
binaries or ignore-unfixed weakening are used. Counts are finding instances,
not distinct vulnerabilities or evidence of exploitation.

Image comparison retains 376 prior application files, 174 Python distributions,
159 OS package versions and 11 other native tools unchanged. Only Syft plus the
explicit provenance/license and inventory verifier differ. This is NOT a clean
full-source rebuild of the entire scanner image and is not deployable.

## Resource and production safety

The initial runtime reserve was below 4 GiB. Two exact, untagged, unused historical
test-build images were archived first; archive descriptors, root filesystems and
28 content-addressed blobs were verified before non-force removal. Available
runtime space rose from 4,276,785,152 to 6,052,589,568 bytes. No volume, production
container, running image, mounted filesystem or broad image prune was touched.
Actual restoration of the archive is NOT claimed. Reserve checks remain required
before each new image build.

No workflow-scope bypass, blocked observer-operator retry, C5E9 receipt retry,
Backend/Telegram redeployment, host-memory activation or Cloudflare change is
part of this segment. FR-07 remains complete; FR-06, pending worker rollouts,
remaining OS/Go findings and host-state/memory/boot gates remain open.

Evidence: `docs/project/runtime/fr06-security-syft-20260930T0548/`.
