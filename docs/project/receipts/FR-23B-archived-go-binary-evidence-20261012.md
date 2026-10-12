# FR-23B — archived pinned Go security-tool binary evidence (2026-10-12)

**Status: PASS for this historical four-binary link-time module-reachability subgate only. FR-23 final security audit remains OPEN.**

Source reference at inspection: protected `ipdomx/AIONEX-AIOS` main `03c32a3797e7117b03ff4324b897b19715ea1ff5`. The original FR-23A validator rejected the actual pinned Trivy `go version -m` header `go1.26.8-X:jsonv2` with exit code **2 / ERROR** because its strict header pattern omitted the colon-bearing Go experiment suffix. The proposed parser admits only the exact known suffix `-X:jsonv2` while retaining single-binary, complete-path/build, tool-identity, dependency-floor and duplicate-module rejection.

## Original immutable input files (on NEW `nc-ph-4354`)

All inputs below are historical PR870 cold-build outputs held beneath `/var/lib/aionex-migration/pr870-build/`. The original files, compiled binaries, and build-provenance records were **read only** in this evaluation; no production image, provider, secrets, or customer data was accessed or changed.

| Tool | Relative evidence path | Real dependency records | SHA-256, exact `binary-modules.txt` bytes |
|---|---|---:|---|
| Trivy | `docker-trivy5/binary-modules.txt` | 375 | `27a5166529f754495c5199d1bbaab66e540c3ebaf4fc17c7691ddd663b253eda` |
| Grype | `docker-grype2/binary-modules.txt` | 295 | `59cf12aa06db6b9b94b0b1e9b7df19aed65c2d4fe0c38c538c516440e1598c94` |
| Syft | `docker-syft3/binary-modules.txt` | 273 | `fe80421c16c13a36d1a34098d89c0d21b48d4863ebe2ff16d3d24ae25461a10c` |
| Gitleaks | `docker-gitleaks4/binary-modules.txt` | 60 | `2ea3b468ebe21bee7e6a3bb4e928cde6acb58a178816391de712ab411a798266` |

The four historical compiled binary files were independently streamed through SHA-256 and **4/4** matched both their own `*-build-provenance.json` reported SHA and their pinned `lock.expected_binary_sha256`:

- Trivy `cf393282a6cf02605112e6886f466cb3c335826dff8172271de3b04441ab8b4d`
- Grype `2ba1610b27fa2478f5eb0a00df4a4c1f8f4fbd690934d8cae1aa8f3fa0943846`
- Syft `3b323bb5f8a59778ae004dc83ef6badadbe7d24d9931f3b41d3c4f4859d9108e`
- Gitleaks `efc12ca6e29d2a8a3cf39f5693ff7c447093e61ed6f35c52356b6911e2b6ecbd`

The **8/8** source `web-dashboard/backend/security-build/{tool}/{go.mod,go.sum}` SHA-256 bytes on NEW matched the corresponding historical provenance locks. These comparisons establish the identity of *the archived builds*, not current production image build provenance or supplier signatures.

## Original policy results using the patched parser

Using unchanged `tests/fixtures/fr23_binary_module_policy.json`, unmodified original real evidence bytes, and the candidate `scripts/security/final_audit_reachability.py` from this patch: CLI **exit 0; status PASS**.

- **Trivy:** legacy `github.com/docker/docker` not linked; containerd/v2 linked at `v2.3.6`; `go.opentelemetry.io/otel*` not linked — three rules PASS.
- **Grype:** legacy docker not linked; containerd/v2 linked at `v2.3.6`; Otel family not linked — three PASS.
- **Syft:** containerd/v2 linked at `v2.3.6`, Otel family not linked — two PASS.
- **Gitleaks:** rardecode/v2 linked at `v2.2.0`, xz linked at `v0.5.15` — two PASS.

The original unmodified validator returned **exit 2 / ERROR: missing go version -m binary header** for the exact same evidence (verified before change); it incorrectly rejected an authentic but nonstandard Go toolchain header.

## Source validation and explicit exclusions

The original FR-23 regression module gained seven cases: positive `-X:jsonv2`, five unrecognized experiment suffix negatives, and concatenated-second-binary-with-experiment negative. The real targeted pytest module passed **70/70**, exit 0, on the isolated NEW scratch root `/tmp/aionex-fr23-go-experiment-20261012`; Python source compilation and JSON fixture parse passed.

Every original provenance receipt explicitly states `production_changed=false` and `full_image_security_passed/accepted=false`. This historical link-time result does **NOT**:
- dismiss or resolve Dependabot alerts #48/#50 or assert VEX/source-level advisory closure (source modules and security advisories require independent scan/remediation);
- verify Trivy/Grype/Syft/Gitleaks against the *current integrated release candidate* or final deployed binaries, full isolated DAST/SAST/SCA/SBOM, FFmpeg/Owner/Web release, FR-06 or FR-21;
- accept FR-23 final security audit, FR-24 whole-customer recovery, FR-09 actual 5,000-user sustained run, or FR-25 launch;
- change the canonical `STATE.json`, mark a batch complete, mutate production services, deploy the archived binaries, or cross into another project.

**Next legitimate acceptance:** once FR-06/FR-21 and integration gates are accepted, the release owner must cold-build the full *current integrated* candidate, bind its four specific scanner binaries and immutable image/source receipts, rerun the unchanged full audit matrix, inspect real source advisories and risk, and write a fresh protected final acceptance. Until then `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED` remains the only justified release status.
