# FR08 Phase36C real Chromium 3D QA: bounded low-power readiness

Date: 2026-10-27 UTC.
Project: AIONEX AIOS. Base main: d6974872c7fc29003a3201fcba351d12ddfd5374.

Code change: only browser scene readiness wait for synthetic 4x CPU-throttled LOW_POWER profile changes from 35s to 80s; desktop and mobile remain 35s. No release performance/FPS/GPU-memory, user interaction, WebGL/error or source security acceptance is skipped or relaxed.

## Genuine independent execution, not a synthetic QA mock

- On separate encrypted FR09 Docker, Node/npm installation used locked package.json/package-lock.json sources from registry.npmjs.org. Exactly 129 npm packages were installed with scripts disabled, then source was rebuilt with npm ci offline and Vite without any network access in the test container.
- An actual Chromium/ChromeDriver/Xvfb software-rendered browser ran all three viewports: desktop 1440, mobile 390, and CPU-throttled low_power 360. Interactions, camera, canvas, rendering, screenshots, final WebGL/browser/performance/rollback gates all ran with the original approved acceptance rules.
- Result: genuine production asset build, browser QA, all three performance profiles, final release_ready on the synthetic procedural 3D artifact PASS. Bundle bytes: 1174128 and elapsed seconds: 32.36.
- Original 3D service test suite plus two bounded-readiness tests: 12/12 passed in disconnected container.
- The actual 3D artifact includes no externally generated GLB assets and did not call any paid Tripo, model, cloud or real customer API. It does not prove GPU hardware, actual model-generated 3D asset quality, physical mobile hardware, tenant approval, or a real customer production deployment.
- This is source-and-asset QA evidence, not user/tenant full application or AIONEX AIOS production final launch acceptance.

Machine-readable verified proof: /mnt/aionex/fr09-isolated-lab-20261011/fr08-real-3d-deps-lab-20261027/FR08-REAL-3D-CANDIDATE-ARTIFACT-PROOF.json
Proof SHA-256: 33630c00df034e264ec1609ce786a726ebaaef4dd3c694bde6eda8f8427b9379
Chromium lifecycle SHA-256: 3b88dc7e9d2f9ee203718ebd4976ee99e8891de67ef957a1424f65e8bfac1572
Unchanged performance gates: PASS for three profiles; no historical FR25 hours modified.

Full project release remains FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED.
