# Phase 34G Production E2E Completion

Date: 2026-08-10 (Asia/Dubai)
Status: **Complete**

## Outcome

Phase 34F license, territory, and provider fallback controls are now closed by
Phase 34G production hardening. The Hunyuan primary path is restricted to the
approved United States control-plane locations, TripoSR is the worldwide
fallback, provider failures are isolated, and both API routing and the worker
fail closed before GPU submission.

No API key, endpoint ID, template ID, provider job ID, user identifier, or
production credential is recorded in this document.

## Acceptance evidence

| Gate | Result |
| --- | --- |
| Hunyuan geography | Control-plane verification returned exactly 12 approved US data centers and no non-US location. Runtime checks succeeded from both the backend and the production worker. |
| Territory routing | EU, UK, South Korea, unknown, and untrusted-country requests cannot unlock Hunyuan and use the permitted fallback. |
| Worker TOCTOU protection | The worker binds validation to its own endpoint snapshot and forces a fresh geography lookup immediately before submission. A primed positive cache cannot authorize submission after drift. |
| Provider isolation | Hunyuan and TripoSR preflight and circuit state are independent. An unavailable provider does not prevent the healthy fallback from starting. |
| Circuit gate | Queued and retried jobs are checked again immediately before submission and are deferred without provider submission when the circuit is open. |
| Clarification flow | Clarification repeats territory routing, current terms acceptance, provider disclosure, fingerprinting, and provider-job reset. |
| Consent UI | Terms acceptance is reset after successful generation and clarification, preventing accidental reuse. |
| Worker health | Health writes use unique same-directory temporary files, mode 0600, atomic replacement, and cleanup. The Compose healthcheck no longer writes the worker's primary health state. |
| TripoSR source | Upstream source, model revision, license hash, requirements, and CUDA base are pinned. |
| TripoSR image security | The independent container gate built the hardened image, generated a CycloneDX SBOM, and passed the HIGH/CRITICAL Trivy gate. Local acceptance also reported 0 HIGH and 0 CRITICAL findings. |
| Full GPU output | The accepted TripoSR live job produced a textured GLB of 3,184,420 bytes; glTF parsing and Blender round-trip validation passed. The accepted Hunyuan production artifact also passed the established GLB validation path. |
| Cancellation | A dedicated safe canary job moved from `IN_QUEUE` to `CANCELLED` with no output and no execution time. |
| Failure behavior | Malformed input terminated as `FAILED` with a bounded top-level infrastructure error; it was not retried. |
| Scale and rollback | The canary reached zero active workers and empty queues. A harmless timeout change was rolled back, with configuration, template, and image digest unchanged. Production uses `workersMin=0`, and the final snapshot had no queued or in-progress jobs and no running workers. |
| Production deployment | Backend, 3D worker, and VIP portal were rebuilt and recreated in dependency order. Owner frontend remained untouched because its deployed source was unchanged. |
| Production stability | Backend, 3D worker, VIP portal, and Owner frontend stayed healthy with restart count 0 for more than three worker healthcheck intervals. Local and public health/smoke URLs passed. |
| Rotation cleanup | Superseded Hunyuan and TripoSR endpoints were purged and deleted only after production validation. Stale secret backup, sensitive canary state, temporary ID files, and isolated test containers/network were removed. |

## Verification summary

- Pull request [#253](https://github.com/ipdomx/AIONEX-AIOS/pull/253) merged to
  `main`.
- All 13 reported pull-request checks passed, including CodeQL, dependency
  security, backend tests, frontend builds, production Docker build, backend
  SBOM/Trivy, the Phase 34F/34G quality gate, and the isolated TripoSR image
  security gate.
- Complete root suite: **638 passed**.
- Focused Phase 34F/34G backend policy and worker suite: **20 passed**.
- Root Phase 34F contracts: **6 passed**.
- Black, Ruff, TypeScript, targeted ESLint, YAML parsing, Bash parsing, pinned
  Actions checks, secret scan, identifier scan, and `git diff --check` passed.
- Thirty-two concurrent health writers completed without corruption or leftover
  temporary files.
- Production provider checks returned true for both the US-only Hunyuan primary
  and TripoSR fallback from the running backend and worker.

## Operational state

- Primary provider: Hunyuan, allowed only when the license, terms, territory,
  owner attestations, circuit, endpoint identity, and live US control-plane
  checks all pass.
- Worldwide fallback: TripoSR.
- Both production endpoints: minimum workers 0, maximum workers 1.
- Final provider snapshot: queue 0, in-progress jobs 0, running workers 0,
  control-plane errors 0.
- Stable emergency Phase 34E rollback images remain available. The pre-34G
  portal snapshot is also retained. The pre-34G backend snapshot is not a valid
  worker rollback because it contains the health-file race fixed in this phase.

## Security notes

- Runtime secrets remain outside Git with file mode 0600.
- Geographic proof is obtained from the provider control plane rather than from
  a declarative environment value alone.
- The RunPod credential is sent in the Authorization header; it is never placed
  in the request URL.
- The worker uses a fresh control-plane read before Hunyuan submission and
  refuses stale client/secret endpoint mismatches.
- The heavy TripoSR image security workflow runs only for TripoSR source or
  workflow changes; ordinary backend or UI changes do not rebuild the 21 GB
  image.

## References

- [RunPod API v1 endpoint update](https://docs.runpod.io/api-reference/endpoints/POST/endpoints/endpointId/update)
- [RunPod API v2 endpoint update](https://docs.runpod.io/api-reference-v2/serverless/update-a-serverless-endpoint)
- [RunPod multi-region serverless guidance](https://github.com/runpod/runpod-plugins-official/blob/main/plugins/runpod/skills/runpod/golden-paths/10-multi-region-ha-serverless.md)
