# FR-06 — explicit native liblzma integrity-metadata coverage

Date: 2026-09-30. Parent: `c4f03eb70814578849b9e424e35c9c174ff179b5` (#813).
State: **isolated correction; HOLD. No merge, deployment, or live-source synchronization authorization.**

## Independently reproduced gap

The #813 verifier accepted an installed-version floor, empty successful `dpkg --verify` output and a loaded-library path match without requiring that the library had an installed checksum entry. Debian documents that `dpkg --verify` checks file contents only when the database contains that file's MD5 metadata:

- https://manpages.debian.org/bookworm/dpkg/dpkg.1.en.html (verify/audit)
- https://manpages.debian.org/bookworm/dpkg/dpkg-query.1.en.html (control-show)

A new non-root, offline experiment used the pre-existing corrected OS-only image `sha256:938a73eb1f68c0b07ee3b14cecdcb76e40f78f5e8a135ce41c4985d5c329e001`. A disposable copy of only the liblzma package database was created on container tmpfs; no native-library bytes, image package database, host database or production files were changed. On the prior verifier, all three incomplete metadata variants passed incorrectly: empty manifest, absent native checksum entry, and missing manifest. The intact control passed and an explicitly wrong native checksum was rejected. This is a verifier fail-open reproduction, **not evidence of corrupted production packages or exploitation of the allocator advisory**.

The initial experiment omitted the copied database's multiarch format marker. Its results and runner v1 are retained as a fixture error, not the accepted reproduction. Runner v2 first proves a clean intact `dpkg --verify` result before testing variants.

## Correction

The verifier now obtains the official package manager's installed `md5sums` control file with architecture-qualified `dpkg-query --control-show`. It requires a bounded, well-formed manifest, exactly one native-library entry, canonical relative paths, and agreement of actual library bytes with the recorded checksum. It supports the Bookworm `/lib` to `/usr/lib` alias but not arbitrary aliases. Missing, duplicate, malformed, unrelated or mismatched coverage rejects acceptance. Package-query and verification warnings also reject acceptance.

The version floor `5.4.1-1+deb12u2`, complete `dpkg --verify` invocation, exact loaded-library binding, SHA-256 receipt, and all nine bounded native compatibility cases remain. No Dockerfile, scanner configuration, exclusion, compiler lock, workflow or package bytes were changed.

MD5 is used only to compare against dpkg's native metadata format, with `usedforsecurity=False`; it is not an authenticity signature or protection against a privileged actor replacing both database and library. APT package authentication and the existing SHA-256 evidence retain their separate roles.

## Evidence and boundaries

- 43 focused tests passed unprivileged, including 19 new cases. They are a subset of the complete Root suite, not additive to it.
- The same five-case native metadata experiment passes after correction: intact accepted; all four negative controls rejected. Nine native compatibility cases also pass with unchanged native SHA-256 `5de60ec1bf90cd3d699188eb9ebb333c22b531394e0b030b55048edbd729ed17`.
- Runner: `tests/fixtures/security_lzma/native_metadata_probe.py`; executed with a read-only verifier bind in an OS fixture, **not a newly installed full application image**.
- Runtime evidence: `/opt/AIOS/docs/project/runtime/fr06-lzma-integrity-20260930/`. Complete Root result, exact-source manifest, quality results and final production comparison are recorded there separately; this document does not pre-attest pending checks.
- No full-image vulnerability scan, native-library rebuild, cold Trivy rebuild, provider call or live-source update was done. The previously retained 200 HIGH/CRITICAL image count remains historical and unremeasured.
- A combined canonical-map/state and Dockerfile/prior-receipt read was blocked before execution during this continuation and was not retried or rerouted. This correction concerns the separately read verifier and its test suite only.

FR-06 and final release remain open. FR-07 retains its previously recorded closure. Exact-head GitHub acceptance is separate for #812, #813 and this correction; keep the held stack unmerged with auto-merge disabled.
