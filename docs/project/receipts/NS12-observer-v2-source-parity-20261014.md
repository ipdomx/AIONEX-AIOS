# NS12 observer v2 protected-source parity — 2026-10-14

- Scope: AIONEX AIOS on NEW `nc-ph-4354` only.
- Base protected main: `bce2fa71285dce8dddad0a41039d2f430fcd4456`.
- The source file in this change is byte-identical to the active read-only observer at `/var/lib/aionex-migration/ns12-local-monitoring-20261008/ns12_observer_v2.py`.
- Runtime/source SHA-256: `e4b0428abb56f0facb407fa74770db2c6b2ddd087b7768c5169caddb76d0e0bb`.
- The checked-in systemd drop-in is byte-identical to the active v2 drop-in; SHA-256 `db6556229425af31f793f8253c0cfcfef73b1867639726fe769e391a573bc5a3`.
- Offline original v2 and compatibility tests: **32/32 PASS**. The repository copies differ from the runtime test copies only in the import path required for the repository layout.
- Natural hourly observations at 13:00 and 14:00 UTC each returned 10/10 expected HTTP results with no anomalies. Receipt SHA-256 values: `2afad4550e65a9afe947ae8f1db9f4b6266db7c130f21c2b57da5a4d4718842a` and `0f9105c44d2127841d3fc7a6c8ad5e856cdab8e5b4fc64cdc2a3e35105b53382`.
- Rollback remains the preserved v1 observer plus removal of the drop-in and daemon-reload. Active and preserved v1 SHA-256 are both `b63ecb52a90f1b396b2c84bca1ca7a27171fa390ae285e11718c9847a835e1b4`.
- This is source custody only. It does not deploy or restart anything, does not erase earlier DNS/pre-connect anomalies, does not certify 72 hours, and does not accept NS12, NS14A, FR06, FR08/FR08E, FR09 actual 5000, or final release.
