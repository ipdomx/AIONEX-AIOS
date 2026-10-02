# FR-06: prove ownership of the native caller's own coordinator descriptor

Base: `4cc8fe8572b267ce0f3d0437e3d305721289c84c`, the current PR838 source. This correction does not retry the platform-refused merge of PR838, change PR835, install the caller or issue a permit.

## Reproduced defect

A child failing to acquire a lock proves contention, not ownership by its parent. The native caller accepted the same coordinator inode after its own lock was released and an independently opened descriptor acquired it. It also accepted a shared lock and loss of the lock immediately after the child probe. One control used an actual independent child process holding the file, not only a second descriptor in the parent.

Eight original regression cases produced six failures and two positive-control passes on the unchanged published source. Failed XML and a separate native before-observation are retained. These are disposable test failures, not evidence that production was exploited or the cause of old missing scheduled receipts.

## Correction and evidence boundary

The caller now checks the kernel's `/proc/<pid>/fdinfo/<fd>` for its own descriptor before and after the contention probe, and immediately after initial acquisition. It requires exactly one whole-file `FLOCK ADVISORY WRITE` record with the actual process ID, device major/minor and inode, together with the descriptor's matching inode field and unchanged private-file metadata. Missing, malformed, truncated, oversized, inaccessible, shared, foreign-owner, range-limited and other lock-personality evidence fails closed. It does not attempt to reacquire a lost lock or repair the coordinator.

Linux's primary documentation describes fdinfo's per-descriptor lock records: https://docs.kernel.org/filesystems/proc.html (section 3.8). The flock API distinguishes independent opens of the same file from duplicates of one open file description. Positive controls retain acceptance of a genuine exclusive lock and its duplicated descriptor.

This remains a cooperative protocol with actual independently accepted initial-install control and role fencing as prerequisites. Sampling cannot prove a lock was never dropped and reacquired between samples; malicious root, a dishonest signer, detached external effects and historical reconciliation are outside this correction. No key, signed permit, historical terminal, enrollment or live installation is created by these tests or this patch.

## Tests actually executed

32 new cases plus the existing native-source, installer and preparation suites: **242 PASS** under UID0, zero failures/errors/skips. These counts overlap any later full-suite run. New cases include real Linux file descriptors, flock, a bounded independent child, identity/readback faults and no-reacquisition assertions. Only the installed-path boundary is modeled; files/locks are actual pytest-owned objects. No production authority or provider call is exercised.

Full nonroot-suite acceptance is not claimed until its actual retained result is added below. Evidence directory: `docs/project/runtime/fr06-recurring-task-health/interactive-coordinator-review-20261002T132838729659Z-ebfc04bb/` on the project server. Existing PR838 and PR835 checks do not cover this correction unless their exact heads change and new checks run. Main/live source, installed MCP, old uncertain runs and the separate credential incident remain unchanged.

## Complete nonroot acceptance

The byte-matched export completed **4182 PASS**, zero failures/errors/skips, as actual UID65534 at `2026-10-02T13:38:23.941375+00:00`. JUnit SHA256 `efa11821928685262677069b06b880710a1ec72c484a282b3c5b0160a24b78c4`. All2703 exported source inputs matched the worktree; the two code/test files were rechecked against that manifest after completion. The32 new cases and242 focused cases overlap4182 and are not additive. No production trust, permit, enrollment or historical reconciliation was exercised. The source receipt was updated only after reading the finished result and XML.
