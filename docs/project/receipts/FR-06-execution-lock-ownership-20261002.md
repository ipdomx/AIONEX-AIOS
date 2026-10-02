# FR-06: verify execution-lock ownership at effect and enrollment boundaries

Base: `d27751fdda1371c2efddd36d090f17b8c6a96947`, current PR838 source. The prior `04f6c273` correction concerned the native installer coordinator, not `ExecutionGuard` or the standalone enrollment challenge lock.

## Reproduced defect

The existing execution guard verified process identity, its internal `_held` flag, private file metadata and named inode identity, but did not establish that its own open file description still held an exclusive flock. The same issue existed at the boundaries of standalone enrollment probing. In disposable temporary directories the new baseline suite had **44 failing cases and three passing controls**. It demonstrated acceptance after explicit unlock, conversion to a shared lock, or acquisition through an independent description of the same inode. The matrix covers all three invocation roles and loss before the call, in either source observation, or after the effect callback. Two cases also demonstrate unproven acquisition entering the guard and creating a journal. No production effects or historical-run claims are involved.

## Implemented correction

The existing guard now requires bounded `/proc/<own-pid>/fdinfo/<owned-fd>` evidence identifying one whole-file `FLOCK ADVISORY WRITE` record for the actual PID/device/inode and the same private empty lock descriptor. It checks immediately after acquisition before effect-journal creation, at existing observation/effect/readback boundaries, and before each partial write and after writing. Missing, malformed, unreadable, shared or foreign lock evidence rejects without reacquiring or upgrading a lock. Existing process, named path and journal checks remain.

Both standalone and active-guard enrollment probes consume this ownership check. Source merge/sync already use the execution guard, so no new activation path, role, permit, CLI or callback authority is added. A lock lost after an effect is not turned into a successful result; the durable intent remains unresolved. A partial journal remains untouched and blocks later use. Errors never authorize replay or erase earlier effects.

## Test evidence and limits

The expanded suite has **70 new cases**, including real inherited-descriptor release by child processes for each role, legitimate duplicate-description controls, missing/malformed kernel evidence, and lock loss during full/partial journal writes. Combined executor, enrollment, source, coordinator and provenance selection: **539 passed**. These are overlapping selections, not additive acceptance counts. Full-suite and nonroot results must be read from the actual runtime evidence, not inferred from this receipt.

These are cooperative sampled checks, not an audit of uninterrupted ownership between samples. They do not defend against malicious root or arbitrary in-process code changing/reacquiring descriptors, fence external providers, install an executor, authorize its initial installation, prove genuine scheduled role adoption, or reconcile historical missing outcomes. Production source, host state, MCP process, signed trust and credentials were not changed. The pre-existing refused PR838 integration has not been retried or cleared.

Linux interfaces used: kernel `/proc` documentation section 3.8 (https://docs.kernel.org/filesystems/proc.html), and `flock(2)` open-file-description semantics (https://man7.org/linux/man-pages/man2/flock.2.html). The local reader accesses only its own lock metadata, never environment variables, raw Docker inspection, user content or credential material.

## Retained evidence

Actual interaction directory: `docs/project/runtime/fr06-recurring-task-health/interactive-executor-review-20261002T154931413001Z-729b690f/`. It retains `execution-lock-before.xml`, `execution-lock-after.xml`, `execution-lock-directed.xml`, and the subsequent exact-source nonroot suite result when complete. The existing review queue remains PR835/PR838. No source-review result is production authorization. FR06/C5D/C5E/C6 and the credential incident remain open; FR07 is preserved.
