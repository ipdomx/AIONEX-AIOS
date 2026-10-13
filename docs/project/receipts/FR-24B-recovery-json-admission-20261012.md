# FR-24B — Sanitized recovery JSON admission integrity (2026-10-12)

**Source-only corrective gate; full customer/platform recovery and release remain NOT ACCEPTED.** Evidence is from `nc-ph-4354` isolated scratch `/tmp/aionex-fr24-manifest-parsing-20261012`; no key, database, network, live offsite object, mounted vault or production service was used.

## Independent real false-green reproduction

Exact protected `ipdomx/AIONEX-AIOS` main source at inspection `cb93ea19d6938b81601fb5a5f1d9135105d2a18f`; original FR24 validator Git blob `58cedbe700fa6f8a04bccb69ffe2056ba669104b`, original test blob `bd12840b788cfd57b345a991c2a47620570ee0da`, unchanged sanitized fixture blob `a9fbdef564ad4f49b103f2117e0c1922d06d299f`.

The original CLI uses normal `json.load()`, which silently accepts *duplicate keys* and lets the later claim override an earlier one, even in the nested `gates.approvals`. In a synthetic manifest where all source-independent dependencies and approvals were otherwise declared true, adding two contradictory `coordinator` keys (`false` followed by `true`) produced **exit 0, `contract_valid=true`, `live_recovery_ready=true`**, although the approval declaration is ambiguous and hence untrustworthy. A raw non-UTF-8 file produced exit 1 with an uncaught Python traceback instead of the documented contract-invalid exit 2.

## Narrow fail-closed correction

- `_load` uses a standard-library JSON object-pairs hook that rejects duplicate key names at **every nesting depth** with `RecoveryContractError`, rather than silently overriding any root, approval or digest field.
- Recoverable malformed UTF-8 decoding is handled by the existing CLI error path as a formatted `FR24_RECOVERY_CONTRACT_INVALID` with exit 2 and no traceback.
- There are **no changes** to AES-GCM encryption envelope, SHA256 manifest canonicalization, backup schema, eleven asset roots, redis-empty strategy, rollback immutability or the existing explicit `gates` admission booleans. No key material is introduced.

Tested published candidate exact code: validator `27d487c14832ed731b1c507b44988794c11e8064`, tests `ca6e59e59055e9351d61edb41aa3c8b0986a4a21`, unchanged fixture `a9fbdef564ad4f49b103f2117e0c1922d06d299f`. **19/19 original+new pytest PASS**; Python `py_compile` and fixture JSON parsing PASS. The original duplicate-approval false positive was independently reproduced against the unchanged original CLI and rejected as **exit 2** against the corrected CLI, with a structured contract error; original clean fixture remains a valid, *synthetic-only* manifest with external gates false.

## Explicit acceptance boundary

An all-true `gates` declaration in a sanitized manifest is **only an operator-provided declaration**, not independently attested key custody, remote object bytes, actual successful host-loss recovery or measured real RPO/RTO. This source validator explicitly marks `synthetic_measurement=true`. Do **not** infer FR-24 full backup/restore, FR-06 guarded cold host, FR-08E integration, FR-09 actual 5000 authenticated users, FR-23 final security lab, NS14A, FR-25 launch or old-host retirement. Full-Router R2 v2 live recovery had a separate recorded platform refusal; do not retry its refused effect through any alternative path. Continue to require an authorized independent full restore/owner journey and real source/image/backup identity evidence before release.

No production, worker, supervisor, secrets, customer/provider, Cloudflare or data changes occurred. CI/merge must follow all five original protected workflows and current required branch rules on the *exact feature head* before source acceptance.
