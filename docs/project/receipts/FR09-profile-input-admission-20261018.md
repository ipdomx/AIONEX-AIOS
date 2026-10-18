# FR09 — Capacity-profile input admission — 2026-10-18

**Status at preparation: local profile acceptance PASS; protected CI and merge are recorded separately.**
This receipt covers profile-input correctness. Actual 5,000-user capacity and full recovery remain unaccepted.

## Reproduced problem and correction

The unchanged source at `881eb7d25b75c6fe3148b85a16da27225f52986b` admitted **11 invalid synthetic inputs** with CLI exit 0 and `heavy_work_permitted=true`: NaN in each of the three SLO fields, fractional/string targets silently coerced to integers, Boolean values coerced to numbers, a negative read ceiling, a string evidence inventory split into characters, and contradictory duplicate JSON fields. Resource measurements and FR08 declarations in this reproduction were synthetic; `load_test_authorized=false` remained intact.

The candidate rejects all **14 invalid CLI cases** with exit 2, `INVALID_PROFILE`, and `heavy_work_permitted=false`. This includes the 11 incorrect preflight results and three cases that previously raised uncaught exceptions. The valid canonical control still passes.

- Integer targets retain their original types; SLOs require finite, non-negative numbers.
- Evidence inventories require lists or tuples of non-empty strings. A direct `dataclasses.replace(...).validate()` regression also rejects a string inventory and preserves valid list/tuple behavior.
- JSON parsing rejects duplicate keys at every depth, including decoded Unicode-equivalent names, and rejects non-finite constants.
- Plan and output files use explicit UTF-8. JSON stdout preserves Unicode values under an ASCII locale. Invalid input fails before runtime storage inspection.

## Verification

On NEW `nc-ph-4354`, in the isolated worktree
`/opt/AIOS/.worktrees/fr09-profile-admission-20261018` based on the immutable source above, Python **3.11.2** and pytest **9.1.1** completed:

```text
python -m pytest -q tests/test_fr09_profile.py tests/test_fr09_profile_input_admission.py -o addopts=
56 passed in 0.32s; exit 0
```

This comprises **24 unchanged original cases and 32 new cases**. Independent offline verification also established:

- **9 valid-profile reports** exactly match the original data, covering 5,000/6,000 users, stricter SLOs, and synthetic dependency/storage PASS and HOLD conditions.
- **9 direct non-finite SLO cases** are rejected.
- Arabic evidence round-trips through both stdout and a UTF-8 file under an ASCII locale; the original fails to read that input.
- `build_ramp`, `_fs_device`, `measure_runtime_free_space`, and `build_preflight` retain identical ASTs.
- Original tests and `PLAN.json` remain byte-identical; compilation and `git apply --check --whitespace=error` pass.

## Evidence custody

NEW root-only evidence directory:

```text
/var/lib/aionex-migration/r1-management-20261008/CONTINUATION-20261018/
```

`FR09-PROFILE-PYTEST.json` records the actual NEW pytest execution.
`FR09-PROFILE-OFFLINE-EVIDENCE-BUNDLE.json` preserves six offline reproduction/comparison evidence files with their individual hashes.

| Artifact | SHA-256 |
|---|---|
| Original `scripts/capacity/fr09_profile.py` | `85c30c3de6f4db969e7eae6caf5d22042eb162b16446d1124e271d533ed253be` |
| Candidate `scripts/capacity/fr09_profile.py` | `a8b00811a08cf1d1339b938a347633c5919aaad2c7047209710b9b3c8bcd3e7d` |
| New `tests/test_fr09_profile_input_admission.py` | `34fba6c81d64022c9c49e2c26a79029ae5ff28a515a37fa3c24a4229b39addcf` |
| Unchanged `tests/test_fr09_profile.py` | `edee26750fc47fe90a0932fa7a0db75308e7c174ce95e2bbce357560af22f210` |
| Unchanged `docs/project/PLAN.json` | `058cdb772e2e3c834f1b64a677e7c2bf0ae2527b966eeca1fe23b0c6146a4ce5` |
| NEW `FR09-PROFILE-PYTEST.json` | `b9ab02b1d0bfafa81fd62a3946f3cf6a61de617266927d5475c779b9ee88a016` |
| Final offline comparison proof | `24687e82827f904035c125c7b88fc1809e5847007e9f9de58fd5832cc9cd61a2` |

## Acceptance boundary

The canonical thresholds, seven-stage ramp, minimum 40 GiB storage condition, default Docker/containerd measurement paths, FR08 dependency, and `load_test_authorized=false` are unchanged. The separate mixed-workload evidence gate is untouched.

This FR09 verification performed no actual load, recovery, production storage measurement, provider calls, deployment, or production mutation. It does not establish FR06/FR08E/FR24 recovery, independent key retrieval, NS12/NS14A acceptance, or final release. The prior Full-Router v2 platform refusal remains binding and was not retried or rerouted. Owner-attested private key custody remains preserved without requesting or exposing key material.

Protected CI for the reviewed commit, normal merge, and post-merge identity verification are separate required records. `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED` and `actual_5000=NOT_RUN` remain unchanged.
