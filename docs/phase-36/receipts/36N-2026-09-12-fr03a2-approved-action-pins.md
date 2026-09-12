# Phase 36N receipt — FR-03A2 approved action-pin transition

Date: 2026-09-12

PR576 updates two security actions using full immutable commit SHAs, but the repository contract was hard-coded to the previous SHAs. This source-only prerequisite keeps full-SHA pinning strict while temporarily allowing exactly the current and approved target SHAs for Anchore SBOM and Trivy across both container-security workflows. No workflow is changed by this prerequisite. A follow-up must remove the legacy pins after the action update merges.
