# FR-06 — Trivy build process lifecycle correction

**Status: locally verified source only; merge and deployment HOLD remain in force.**

## Continuation and scope

Reviewed the live project report, STATE, complete 26-batch/62-capability PLAN, source index, current server state, and GitHub candidates before this change. FR-06 remains the first unfinished batch. FR-00 through FR-05 and FR-07 remain complete in the canonical journal; their deployment and synthetic-account acceptance were not repeated.

This isolated branch starts at PR #811 head `7d78a7fb0fc419962409c8f5bbe1da519b8e6f80` and consequently contains the held PCRE2/Trivy stack. The live source remains `1d24d13701a5c70c25377b67b5563522b40ac95b`; it was not synchronized to main. The new change modifies only Trivy cold-build process ownership and its tests. No shared Gitleaks runner, Syft build, workflow, vulnerability exclusion, detector, rule, module lock, compiler version, binary fingerprint or production configuration changes are included in this correction.

## Defect reproduced before the correction

The previous cold-build helper called the shared `subprocess.run(timeout=...)` runner. Timeout stopped its immediate child, but nested compiler/test processes could continue executing after the helper had returned a TIMED_OUT receipt.

Two native offline regressions, covering a child and a grandchild, failed on the unmodified parent source. A release barrier was opened only after the timeout returned; both descendants then wrote a synthetic marker. The fixture explicitly verifies that the leaf started, is finite even against the broken implementation, and uses no network, provider, scanner or production resource.

## Implementation and limits

`run_cold_process` starts a private session for the trusted compiler/test command. `waitid` with `WNOWAIT` observes completion without reaping the leader, preserving the identity used for process-group cleanup. The owned group is signaled before the direct child is reaped on ordinary completion, nonzero exit, timeout, or a caught Python interruption. The default Linux child-reaping policy is required; a lost child-ownership observation fails closed without signaling a potentially recycled group identifier. Invalid deadlines and uncertain cleanup cannot produce acceptance.

The external cold-command limit remains 1800 seconds, the Go package-test limit remains 120 seconds, and all seven selected upstream packages, reproducible binary checks and source/module checks remain unchanged. Existing diagnostics retain their create-only receipts, bounded JSON-escaped log tail and distinct PASSED/FAILED/TIMED_OUT results. Seven existing mock bindings were moved to the new helper; no acceptance assertions were removed or relaxed.

This is **not a cgroup, hostile-process sandbox, descendant-reaping certificate, or host-drain proof**. A deliberately detached session, abrupt supervisor death, or an uninterruptible kernel operation is outside the demonstrated guarantee. An enclosing disposable build is still required. Native tests prove the stated finite process/control cases, not every Go process lifecycle or whole-container shutdown.

## Verification retained on the server

Evidence root: `/opt/AIOS/docs/project/runtime/fr06-trivy-owned-processes-20260930`.

| Evidence | Result |
| --- | --- |
| `baseline/junit.xml`, `baseline.log` | Two native late-write regressions failed before the fix; exit 1 retained. |
| `focused/junit.xml`, `focused.log` | 66 cases passed, including 16 new lifecycle cases. |
| `full-root/result.json`, `full-root/root.xml`, `full-root/root.log` | 3310 Root cases passed; zero failures, errors, or skips. |
| `full-root/source-manifest.json`, `tested-code-hashes.json` | 2620 source files matched the separately writable test copy; all three changed code/test files still match their tested hashes. |
| `quality/result.json`, `quality/ruff.log`, `quality/mypy.log` | Ruff and Mypy passed. |
| `production-observation.json`, `production-comparison.json` | The same 40 container identities, images, start times and restart counts; 36 running, zero running-unhealthy; live source unchanged. |

Tests ran as `nobody` on owned isolated paths, with the full Root suite using a separately writable source copy. The 66 focused cases and 16 new cases are subsets of 3310, **not additional test totals**. Coverage includes successful/nonzero leader exit, nested descendants, caught interruption, ownership loss, cleanup denial, invalid deadlines, reserved group identity, and survival of an unrelated sibling process.

The four stopped initialization/reconciliation containers were not restarted. Two retain historical unhealthy health states; these are reported as stopped and are not silently reclassified as healthy. The first metadata query failed because some containers have no Health field; the corrected metadata-only query preserves missing healthchecks as null.

## Security and deployment boundary

The retained parent image scan at `fr06-security-trivy-20260930T1235/full-scan-final/result.json` still reports **200 HIGH/CRITICAL instances**, including 144 OS-package instances, while the Trivy executable itself has zero. No vulnerability was excluded, and `ignore_unfixed` was false in that retained scan. This process-lifecycle change did **not** rerun the scan or reduce that count. It also did not repeat the pinned Trivy cold binary build. A previously passing parent-head check is not acceptance of this new commit.

The new review remains HOLD. No merge, auto-merge, production deployment, live-source synchronization, database migration, host memory/swap operation, provider action, or blocked operation was performed. FR-06, full-host closure, the expanded 1000-user capacity profile, and the final release remain open.

## ملخص الاستمرارية

أُثبت عيب استمرار عمليات بناء فرعية بعد انتهاء المهلة بحالتين فاشلتين، ثم صُحح داخل فرع مستقل. نجح 3310 اختبار Root كاملًا، تشمل 66 اختبارًا موجهًا و16 حالة جديدة، مع نجاح Ruff وMypy ومطابقة المصدر المختبر. الإنتاج لم يتغير. يستمر تجميد الدمج والنشر، وتبقى 200 نتيجة أمنية من الفحص السابق دون ادعاء إعادة فحص أو خفض عددها. تُراجع بوابات الرأس الجديد مستقلة عن #811؛ لا تعاد FR-07 أو العمليات المحجوبة.
