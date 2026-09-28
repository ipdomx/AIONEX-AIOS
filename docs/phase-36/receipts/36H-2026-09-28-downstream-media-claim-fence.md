# Phase36 downstream media maintenance fence — FR-06C5D10A

Source-only correction based on accepted PR770/main0151b1aa. Eleven downstream
media claim paths and six lease-reaper paths now honor the existing shared
Studio-request maintenance lock in their own PostgreSQL transaction. The
versioned authority declaration is not widened and no provider drain is claimed.

Unchanged-source reproduction: 21 failures in32 private PostgreSQL cases;
corrected:32/32; expanded:61/61; combined existing audio/image/video regressions:
274/274, including the61 new cases. No provider network calls, customer data,
production deployment, schema change, host cutover or FR07 re-execution occurred.

Detailed source and retained evidence boundaries:
`docs/project/receipts/FR-06C5D10A-downstream-media-claim-fence.md`.
