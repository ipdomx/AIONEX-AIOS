# Phase 36N / FR-06 — native integrity metadata follow-up

2026-09-30. Parent #813 at c4f03eb70814578849b9e424e35c9c174ff179b5.

An isolated native metadata experiment reproduced three missing-checksum acceptance gaps in the liblzma verifier. Explicit installed checksum coverage and actual native-file comparison now reject them, without modifying the package, version floor, Dockerfile or scanner rules. All nine bounded native compatibility cases remain successful. Focused source validation: 43 tests, including 19 new cases. Full-suite and exact-head CI results are maintained separately and are not implied by this receipt.

See `docs/project/receipts/FR-06-lzma-integrity-metadata.md` and the reproducible `tests/fixtures/security_lzma/native_metadata_probe.py` for scope, official documentation, fixture correction, runtime evidence and limitations.

No new CVE count reduction, full-image scan, merge, production deployment, provider operation or source synchronization is claimed. The held stack remains draft. FR-06 remains open; FR-07 retains its recorded closure. No final-release status is granted.
