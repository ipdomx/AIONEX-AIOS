# FR-25 Academy approved-package access integration

Generated: 2026-10-03T07:13:15.372269+00:00

Scope: serialized FR25-owned integration requested by FR17. No FR17-owned source was edited.

Change:
- Ordinary academy:read package download now requires status == approved.
- Ordinary academy:read package site access now requires status == approved.
- review_pending remains available only through existing assessor/reviewer flows that require academy:assess; teacher answer-key review behavior is intentionally unchanged.
- Private _private/ site assets remain denied to ordinary site access.

This receipt is source-level integration evidence only. It does not claim live deployment or FR17 final closure.
