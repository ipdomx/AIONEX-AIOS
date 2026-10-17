# FR09 / FR16C — release evidence admission hardening

Date: 2026-10-17  
Repository: `ipdomx/AIONEX-AIOS`  
Verified host: NEW `nc-ph-4354`  
Immutable base: `6a22bc2e81a715a1b2faf93e05b216f1c8cfce48`  
Scope: offline evidence parsing and candidate output freshness. Parent FR09 and FR16 runtime acceptance remain open.

## Why this change is necessary

Two acceptance boundaries admitted misleading evidence. FR09 parsed receipt JSON with the default duplicate-key behavior, which discards an earlier value when a later field repeats its name. The Blender candidate reused existing output directories and accepted files based on existence and minimum size; a successful subprocess exit could therefore reuse an old output, follow an output symlink, or overwrite a different file through a manifest symlink.

The original behavior was reproduced on the immutable base before the source was replaced in the isolated worktree. All reproduction inputs were synthetic fixtures. No capacity workload, renderer executable or provider was invoked.

## FR09 JSON admission

Both `--mixed` and `--read-only` now read UTF-8 JSON through an object-pairs hook that rejects duplicate fields at every object depth, including objects inside arrays and names expressed with equivalent Unicode escapes. Identical repeated values are rejected as ambiguous as well.

The existing CLI error contract remains exit `3`, `INVALID_EVIDENCE`, and an error type only. The evaluator, thresholds, clean fixture semantics and original test functions are unchanged. The hook operates at the CLI text boundary; `evaluate(dict)` cannot recover duplicate fields already discarded by an external parser.

| Verification | Result |
|---|---|
| Original CLI, 14 ambiguous synthetic inputs | All 14 incorrectly returned exit 0 / `FULL_MIXED_ACCEPTED` |
| Corrected CLI, the same 14 inputs | All 14 returned exit 3 / `INVALID_EVIDENCE` |
| Added CLI regressions | 16: 9 mixed, 5 read-only, 2 malformed UTF-8 |
| Focused existing and added FR09 tests | 71 passed |

The actual capacity target remains 5,000 authenticated active users, at least three projects and three conversations per user, 15,000 durable jobs and a 15-minute steady window. These parser fixtures do not establish those measurements.

## FR16C candidate output freshness

The runner now atomically reserves a new destination with mode `0700`. Existing destinations, including empty directories, workspace root itself and destination symlinks, are rejected. Callers must choose a new destination for every run.

The script and manifest are created exclusively with mode `0600`, so a collision is rejected before an existing file or symlink target can be overwritten. Output inspection uses a no-follow, nonblocking descriptor, requires a regular single-link file and derives its size and hash from that descriptor. It checks identity and metadata during the read and closes the descriptor on success and rejection.

The public constructor and render signatures, scene script, preflight, artifact shape and relative artifact names remain unchanged. Repository search found no production caller requiring migration from the old destination-reuse behavior.

| Synthetic boundary scenario | Original source | Corrected source |
|---|---|---|
| Existing outputs with zero-exit subprocess producing nothing | Accepted | Rejected before subprocess |
| Output symlink to a previous file | Accepted | Rejected |
| Manifest symlink to a different file | Wrote through the link | Rejected, target preserved |
| New regular outputs | Accepted | Accepted with matching hashes and sizes |

Sixteen added cases cover destination collisions and races, output links, non-regular files/FIFO, manifest collisions, descriptor closure, file replacement during inspection, and clean successive runs. The focused suite including the existing candidate, interactive foundation and asset pipeline tests passed **33 tests**.

This increment verifies freshness and each file's identity at inspection time. It does not validate GLB/PNG format, establish a real generated scene, seal both output files atomically against a continuing same-permission writer, or establish network/CPU/RAM/GPU isolation. Hunyuan's security quarantine is unchanged. The real current renderer and browser acceptance remain open.

## Executed validation

Executed on NEW in `/opt/AIOS/.worktrees/release-evidence-admission-20261017`, using the existing Python **3.11.2** test environment for local runtime compatibility:

```text
python -m pytest -q tests/test_fr09_evidence_gate.py tests/test_fr09_profile.py
71 passed in 0.84s

python -m pytest -q tests/test_fr16c_blender_output_freshness.py tests/test_phase36i_blender_candidate.py tests/test_phase36i_interactive_foundation.py tests/test_phase30b_3d_asset_pipeline.py
33 passed in 0.39s
```

The local commands also disabled pytest's cache and used a separate temporary test directory. Repository CI retains its original Python 3.12 workflow and full test commands. CI results are a separate merge gate; this receipt reports the local executions above.

Independent review verified the immutable source identities, unchanged evaluator/thresholds and original tests, final renderer descriptor handling, caller compatibility and the intentional new-destination requirement.

## Source identities

| Source | Original SHA-256 | Corrected SHA-256 |
|---|---|---|
| `scripts/capacity/fr09_evidence_gate.py` | `ce97b565fd55824311e8463287b64dd315774182963e03c81943d95922dc5ca8` | `1fa0fae758570eda0ff9d9a095b17fddea3de6432dbc90922161662e52b70d3a` |
| `src/aios/three_d_web/blender_candidate.py` | `7f4fc35687e6f5d5183dbce0a9eed322fd095bbe0860243146740ef96f3823f4` | `27c07d6659acf2404df68d2b97401dfcfc1285a46ccb19a59b469363f2337c08` |

## Retained evidence and release boundary

Evidence directory on NEW:

`/var/lib/aionex-migration/r1-management-20261008/RELEASE-EVIDENCE-ADMISSION-20261017`

- `FR09-ORIGINAL-REPRODUCTION.json`: SHA-256 `56e880bc6b341b1e17b4c0f83b5a81aa4e0c02f6e31966e94d1fbf54969e466f`.
- `FR09-FIX-VALIDATION.json`: SHA-256 `1ba699737a56153adbc716311c4804b83d03a45c4f6448052580fdae05303629`.
- `FR16-ORIGINAL-AND-FIX-REPRODUCTION.json`: paired synthetic observations from the unchanged and corrected source.
- `FR16-FIX-VALIDATION.json`: SHA-256 `82c174c2500d30f3796719ab26783d4e2962064fd2b9b07d11f0f6c886c0738a`.

At the review's 12:00 UTC natural NS12 observation, the Owner boundary had a DNS/pre-connect timeout while nine other targets were expected. The automatic diagnostic's later 302 does not replace that primary failure. The historical clean tail of 23 is preserved, current clean tail is zero after this interruption, and the previous October 19 candidate is invalidated. This source change does not modify the observer or its acceptance thresholds.

Production application versions, services, provider activation and DNS/Cloudflare configuration were not changed by this validation. Full capacity, current renderer, full recovery, 72-hour continuity and final release acceptance remain unclaimed.

## متابعة عربية

أُصلح قبول JSON الملتبس وقبول مخرجات الرندر القديمة والروابط، وثبتت النتائج باختبارات محلية عددها104. هذه دفعة تطوير لصدق قبول الأدلة؛ تبقى شروط التشغيل الفعلي والسعة والاستعادة والمراقبة والإطلاق الكامل مفتوحة في الخريطة الموحدة.
