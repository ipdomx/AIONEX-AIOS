# FR-06C5D8A2B2 — Studio no-replace archive publication

Canonical reviewed receipt:
`docs/project/receipts/FR-06C5D8A2B2-studio-no-replace-publication.md`.

Studio's existing storage API delegates to an exclusive staging and no-replace
publisher with pinned directory descriptors, checksum readback and explicit
uncertainty on sync/cleanup failures. Existing archives are never overwritten.
This is not execution-resource settlement, production deployment or full-host
drain. Current acceptance and unresolved gates remain in the single Project Hub:
`docs/project/PROJECT-REPORT.md` and `docs/project/runtime/`.
