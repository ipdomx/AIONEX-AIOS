# Phase 34F — License, Region and Provider Policy Gate

## Release decision

AIONEX AIOS does not treat Hunyuan 3D 2.1 as an unrestricted commercial dependency. Hunyuan routing is fail-closed by default and cannot become eligible until the Super Owner explicitly records all required acknowledgements in the 3D control plane. The production 3D service remains functional through the MIT-licensed TripoSR fallback.

## Pinned license evidence

### Tencent Hunyuan 3D 2.1

- Source revision: `82920d643c0dc2f7bfd7255f45f62d386edfe60c`.
- License SHA-256: `b79ac5e11ce063b6c6570dbe9686a45a03ba08bd248aa6aa82fb342a23a81c0c`.
- Exact license copy published with the portal: `/legal/tencent-hunyuan-3d-2.1-license.txt`.
- The license territory excludes the European Union, United Kingdom and South Korea.
- The platform therefore treats all EU ISO alpha-2 country codes plus `GB` and `KR` as mandatory exclusions that Owner configuration cannot remove.
- Unknown jurisdiction is never sufficient for Hunyuan routing.
- Hunyuan use additionally remains disabled until the Super Owner confirms the operator legal name, acknowledges the license obligations, and attests that the commercial eligibility / separate-license condition is satisfied for the organization.
- The user disclosure identifies the service operator, Hunyuan model, machine-generated nature of output, the applicable license, and states that Tencent is not affiliated with, sponsoring, or endorsing the service.
- The platform prevents Hunyuan artifact-link issuance if the current request jurisdiction is no longer permitted.

### TripoSR

- Source repository revision: `107cefdc244c39106fa830359024f6a2f1c78871`.
- Source license SHA-256: `ade0a66629bdd7e01e46b3296b3851cff0fd27989bca53da470ad6e96ed620fb`.
- Model snapshot revision: `5b521936b01fbe1890f6f9baed0254ab6351c04a`.
- Exact MIT license copy published with the portal: `/legal/triposr-mit-license.txt`.
- The fallback Docker build vendors the pinned source, bakes the pinned model into the image, and emits a textured GLB whose manifest truthfully reports `fallback_used=true`, `fallback_provider=triposr`, and `license=MIT`.

## Jurisdiction enforcement

Country resolution is server-side and fail-closed. The API accepts `CF-IPCountry` only when the complete protected Cloudflare edge header set is present (`CF-Ray` and `CF-Connecting-IP`). Direct/internal requests, incomplete edge headers, unknown codes and anonymous markers are treated as unknown and can route only to the permissive fallback. Registration telemetry remains audit data and cannot unlock Hunyuan.

Provider selection is evaluated before an input object is stored or a GPU job is created. A provider must satisfy all of the following:

1. Model license permits the resolved jurisdiction.
2. Required Owner attestations are present.
3. Provider endpoint credentials/configuration exist in the protected RunPod secret file.
4. The provider circuit breaker is available.
5. Current third-party 3D terms are explicitly accepted for the request.
6. For Hunyuan, the RunPod control plane reports a non-empty US-only `dataCenterIds` set for the configured endpoint.

When Hunyuan is not permitted, configured, region-verified, or available, the request routes to TripoSR. If neither provider is permitted/available, the API fails closed and does not submit GPU work.

## Compute-region enforcement

The dedicated Hunyuan Serverless endpoint is constrained through RunPod GraphQL `dataCenterIds` to 12 US data centers, with no non-US location present. Its minimum worker count remains zero and maximum remains one. The application revalidates the control-plane configuration on a bounded cache and fails Hunyuan closed if the endpoint is missing, the list is empty, any location is non-US, or the control-plane check fails. The TripoSR fallback does not inherit the Hunyuan territory restriction because its pinned source/model are MIT-licensed.

Endpoint, template and job identifiers are operational secrets: they remain only in protected server files and acceptance evidence, never in Git.

## Final live fallback acceptance

- Security-clean fallback image: `ipdomx/aionex-triposr@sha256:e07f4558089de625817e58729d192eea6740889a0f17d3029a4b32026c8f0e4f`.
- Trivy `0.72.0` gate against that immutable image: **0 HIGH / 0 CRITICAL**.
- The protected production fallback template is pinned to the immutable digest above.
- The retained production fallback endpoint is `workersMin=0`, `workersMax=1`, `idleTimeout=5`.
- Live acceptance completed without retry or failure.
- Live output: `3,184,420` byte GLB, SHA-256 `c6699ab3a10a7e0601ed6df0fcf7b23a2409c060f0e0cd606959ba63bcd4950b`.
- Manifest truthfully reported MIT TripoSR fallback, one mesh, one material, one PBR material and one embedded texture at `1024x1024`.
- `gltf-transform inspect` validated glTF 2.0 mesh/material/base-color texture content. Blender `4.0.2` imported the same accepted GLB successfully.
- After the job, RunPod reported no queued/in-progress/running/unhealthy work, confirming scale-to-zero without deleting the retained endpoint.
- The replacement Hunyuan production endpoint is `workersMin=0`, `workersMax=1`, `idleTimeout=5`; an independent GraphQL read confirms exactly 12 US `dataCenterIds` and no non-US location.
- The protected production secret file references only the retained Hunyuan and TripoSR endpoint IDs plus the RunPod credential, remains mode `0600`, and is excluded from Git.

## Owner controls

The Super Owner 3D page controls service enablement, eligible plans/users, quotas, spend, retries, cleanup, provider circuits, fallback enablement, Hunyuan license acknowledgement, commercial eligibility attestation, operator legal-name confirmation, mandatory-plus-additional excluded country codes, and the current third-party terms version. Mandatory Hunyuan license exclusions are enforced in backend normalization even if the UI payload attempts to remove them.

## User terms and disclosure

Every new 3D generation requires acceptance of the currently configured third-party model terms version. The project UI displays the selected provider, model, license, jurisdiction used for routing, and Hunyuan non-affiliation disclosure before generation. The public Terms page includes the model-service restrictions and links to complete upstream license copies.

## Acceptance gate

Phase 34F is complete only when:

- unit/integration/static contract tests prove fail-closed territory and terms behavior;
- Hunyuan endpoint location is control-plane verified as US-only with `workersMin=0`;
- TripoSR fallback image is rebuilt from pinned inputs, pushed by digest, and deployed to a scale-to-zero Serverless endpoint;
- live TripoSR inference produces a real textured GLB validated by glTF Transform and Blender;
- production secret contains both endpoint IDs without exposing credentials or identifiers;
- Owner and user frontends build with six complete locales;
- all repository CI/security checks pass after merge.


## 2026-09-03 TripoSR supply-chain refresh

- A refreshed Trivy gate detected `CVE-2026-9856` as HIGH in `transformers==5.5.4`; the advisory reports the fixed line at `5.10.0`.
- `5.10.0` is yanked upstream, so the image now pins the minimal non-yanked fixed release `transformers==5.10.1`.
- The image build now runs `pip check` and imports `ViTModel` from the exact API used by vendored TripoSR before model baking.
- Container-security actions are updated to the current Dependabot-proposed immutable SHAs, with matching contract assertions.
- Production provider activation is unchanged; this maintenance does not trigger a GPU/provider request or spend.

### Protected merge and production template activation — 2026-09-03

- PR #543 passed all 16 protected checks, including the rebuilt TripoSR source/SBOM/Trivy gate and Production Docker Build, and merged to `main` as `7db9fde112e58d660c4eb614a420795bed09b7b1`.
- The exact server-built release image is `ipdomx/aionex-triposr@sha256:66d8a17e74377a0335bf7fda22847afe4ee7ae30431eb6f09f6c99c03389f440`; runtime metadata confirms `transformers=5.10.1` and the exact vendored `ViTModel` import passes.
- A fresh Trivy `0.72.0` scan of that exact local release image completed with **0 HIGH / 0 CRITICAL**.
- The image was pushed by immutable digest, then the already-bound production TripoSR template was changed from the prior `sha256:e07f4558089de625817e58729d192eea6740889a0f17d3029a4b32026c8f0e4f` image to the new immutable digest above.
- Template activation preserved every non-image mutable template field exactly; the endpoint remained `workersMin=0`, `workersMax=1`, `idleTimeout=5`.
- No Serverless generation job was submitted for this security deployment. Post-activation health reported `inProgress=0`, `inQueue=0`, `retried=0`, with no unhealthy/running worker, and application policy reports `triposr_configured=True` while Hunyuan remains fail-closed (`hunyuan_configured=False`).
