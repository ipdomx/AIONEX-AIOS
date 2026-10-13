# FR08E independent worker, media, and AI subgates — 2026-10-13

## Scope

This receipt reconciles already-completed, independently preserved FR08E subgates from NEW (`nc-ph-4354`). It does not expand any result into full FR08E acceptance or FR09 capacity acceptance.

## Preserved bounded evidence

| Subgate | Preserved result | Canonical evidence |
|---|---:|---|
| Native worker fencing | PASS 13/13 | checkpoint SHA256 `fae8cfda147cbf2f7129c34617ced886d858cd7cf225e846f4eb2f1e43185507`; proof SHA256 `5ce176849db0e78f3205d9795fb1b8e25f739f2bdba9d59a3215f23a42115a19`; event `fr08e-native-worker-fencing-subgate-20261011T201557Z` |
| Native FFmpeg media adapter | 17 operations / 15 documented outputs | checkpoint SHA256 `560f683a3df4888b1e27f77a3571255f399b15a4b0e802732596916fbab19eb2`; proof SHA256 `e874734f0be17a2439863fd7fe9ff99283d0e3f71802605d35dc870cea27a456`; event `fr08e-native-ffmpeg-media-subgate-20261011T202056Z` |
| Current media orchestrator | PASS 34/34 | proof SHA256 `19c3f25288a15ff400cd9da4d3862424567ad46206cfb87bc8531c2926a1fd05`; event `fr08e-current-media-orchestrator-subgate-20261011T212345Z` |
| Local Ollama inference | PASS 35/35 | checkpoint SHA256 `3d881710d0b78fbf2b0162c55c405128d953e913b348f2c3772ca8c1f1e1ed4f`; proof SHA256 `3fae91ba475e32532843bd7b77a75e881d55570fecec6718885c50cfa703b0fd`; isolated model copy, no production Ollama, provider credential, paid request, or external network use |
| Full-app synthetic boot and authenticated journey | PASS 20/20 | checkpoint SHA256 `495c104fe341a4dc63654e2a58be7a0723b8071a9badbcbc00a87bea2d48f1bd`; proof SHA256 `83d6d504b4c3765371e82ba9bf36b78ffa914288ff1180ca928608c505c651e6`; event `fr08e-full-app-synthetic-subgate-20261011T230730Z` |
| Native AI integration | PASS 10/10 | proof SHA256 `96940195373e1e170b6f4e8ed722d0778386b2a34cea3e1e3041d1456ed0b438`; event `fr08e-native-ai-integration-subgate-20261012T010209Z` |
| Phase 36C durable authority | PASS 14/14 | proof SHA256 `39c31cf94dd157655924f9f0c47812a9d6834f73214ae1bd20979e5121b975a2`; event `fr08e-phase36c-durable-authority-subgate-20261012T023905Z` |
| Phase 36C current-model evidence | PASS 16/16 | proof SHA256 `cd812cb0ff05345003999b86aa4c623bad80e19a768c76666cc83cb0177b2a69`; event `fr08e-phase36c-model-evidence-subgate-20261012T032242Z` |
| Phase 36C provider-credit policy | PASS 8/8 | proof SHA256 `6193af5c82302d5b6b5c52f03c763f26e61366d0b77df60f0707f4fa0c647131`; event `fr08e-phase36c-provider-credit-subgate-20261012T041825Z` |

The case and operation counts above are independent bounded checks; they are not user counts and must not be summed or interpreted as the 5,000-user workload.

## Isolation and cleanup boundary

The preserved executions used the isolated NEW laboratory with native source/projections and unchanged original tests where recorded. They made no external provider calls or paid requests, did not use customer/R2 data, and did not mutate production. Laboratory containers, data, media, and transient signatures were cleaned. The production observation remained 36 containers Up / 35 Healthy / 0 bad.

## Acceptance boundary

The following remain open and are not established by this receipt:

- full independent FR08E acceptance;
- full customer R2 recovery with authenticated Owner/customer UX;
- recovered live worker/media asset chain and host-loss/full-router proof;
- FR06 guarded cold-host and NS14A acceptance;
- FR09 actual 5,000 authenticated active users for 15 minutes with 15,000 durable jobs and all PLAN SLOs.

Accordingly, `FR08=in_progress`, `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED`, and `actual_5000=NOT_RUN`. Heavy workload remains inadmissible until the independent FR08 admission gates are complete.
