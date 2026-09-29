# FR-06C5E8 — journal-bound mapper and volatile volume key

## Scope

This part follows PR #786 candidate `c00b75f714b65ed6c6a325f1c8d14754fe26ced4`. It adds only `create_swap_mapper` to the C5E2 reviewed step order and implements a single-step mapper journal. C5E6 backing and C5E7 loop journals and locks remain held and must be finalized before preparation. It does not format swap, enable swap, mount tmpfs, install boot units or compose the complete memory transition. FR-07 remains complete; FR-06 is not closed.

## Implemented behavior

The mapper is created with a name derived from its canonical operation UUID. Native libcryptsetup produces the corresponding `CRYPT-PLAIN-...` device-mapper UUID during creation, rather than applying an ownership label afterwards. Both its exact UUID and its parent loop/backing graph are independently checked. An existing, foreign, partial, suspended or differently configured mapper is rejected, including on reopening a pending journal. No device is adopted merely because a filename exists.

The fixed profile is PLAIN AES-XTS with a 512-bit volume key, 512-byte sectors and the exact accepted loop capacity. The loop descriptor is retained through the native library operation. Public status metadata is parsed with strict operation-specific header checks; no volume-key query or device-mapper table export is performed.

The volume key is requested directly into an anonymous mmap after successful mlock, MADV_DONTDUMP and MADV_DONTFORK. It is passed once as a native pointer, never converted to Python bytes/text or supplied through argv, environment or a key file. The private page is zeroed before unlocking and unmapping, including when generation or the consumer fails. Native creation disables core dumps for its process. The native library and kernel have their own copies; this does not prove that every copy in every subsystem is locked, nor defend a live process against root or provide persistent key custody.

Every native action requires the exact durable intent and independently supplied closed context. Read-only reconciliation never creates a new key or retries an interrupted effect. Removal is refused with mapped children, mounted filesystems, swap consumers or an open block descriptor. Parent resources remain owned and allocated; mapper removal does not erase their backing.

The first native run revealed that libcryptsetup retries a busy deactivation internally even with flags zero. The final implementation uses one key-free libdevmapper DM_DEVICE_REMOVE task, with neither retry_remove nor deferred_remove enabled. It independently verifies the UUID before submitting the operation-specific name. The kernel rejects simultaneous name and UUID lookup, while UUID-only removal leaves a mapper node behind in a no-udev guest; both failed experiments are retained. Successful native removal updates only that task's device-node bookkeeping. Frozen-writer authority is still required across observation and removal; markers and advisory locks do not exclude a privileged ABA/name replacement.

A separate negative test showed that separately valid mapper/loop namespace reports were not cross-joined in the first draft. The final reader requires the same namespace in both reports before binding or effect. This is an isolated synthetic regression, not an observed production incident.

## Acceptance

- Focused tests cover actual protected anonymous memory and zeroization, actual fork rejection, entropy/locking failures, strict mapper identity and cipher profiles, parent/evidence/context changes, consumer denial, interrupted actions and explicit recovery. Counts and exact source hashes are retained in the runtime acceptance manifest.
- Native QEMU acceptance uses libcryptsetup and libdevmapper against Linux 6.8.0-142, not a fake device backend. Eight cases include create/remove with a private random key, active encrypted swap, an ext4 mount, a busy descriptor, and four child-process deaths before/after apply/undo. All kernel mutation occurs inside the no-network guest with its own virtual disk.
- An old native run that functionally passed is not accepted as proof of single-attempt removal; its retry diagnostics are retained. Subsequent failed identity/node experiments remain retained rather than suppressed.
- The full root suite is run as nobody on a separate writable source snapshot; production source ownership is not changed. Native VM code is compared byte-for-byte with the accepted source before final evidence is recorded.

## Sources and boundaries

ABI declarations were checked against downloaded distribution development headers, extracted privately without installing packages. The libcryptsetup public API documents raw volume-key activation and the PLAIN no-on-disk-header format; the package header defines the libdevmapper task API.

- https://mbroz.fedorapeople.org/libcryptsetup_API/group__crypt-activation.html
- https://mbroz.fedorapeople.org/libcryptsetup_API/group__crypt-type.html

The operation-specific mapper name differs from the legacy fixed boot-plan name. No existing boot unit is silently retargeted; integration of that identity with the full plan and reboot recovery remains required. No host swap/loop/mount, production provider, maintenance transition or existing deployed service is changed by this part. Incomplete library creation may leave an unrecognized partial mapper, which remains blocked for separate reconciliation; no automatic cleanup is used to manufacture success. Host power loss, host boot, C5D provider/resource drain and encrypted host-state cutover, plus C6 final acceptance, remain unverified.


## Additional process-dump security review (2026-09-29)

The original mapper implementation set RLIMIT_CORE to zero but left PR_GET_DUMPABLE at one during native-library initialization, key consumption and cleanup. A new nonroot subprocess regression reproduced that state without creating a kernel mapper or exporting key payload. Linux core(5) documents that RLIMIT_CORE does not limit cores piped to a userspace handler; the process-local dumpability control is therefore required as well.

The revised native creation path establishes PR_SET_DUMPABLE=0, reads it back, sets the core-file limit to zero and verifies that limit BEFORE loading/initializing the crypto library. Failure of any check stops before crypto or key generation. The process remains nondumpable after cleanup; no host core_pattern, sysctl or collector is modified by the implementation. Privileged memory inspection, later credential changes, kernel/native-library copies and boot key custody remain outside this proof.

Seven new tests cover native process state and denial of each protection step. A separate tagged QEMU guest additionally exercises a real pipe-based core handler using synthetic crashing processes with no keys: RLIMIT_CORE=0 alone invoked the collector once, whereas the protected process did not invoke it. The collector discarded the memory payload instead of saving it. Guest core settings were restored; the host configuration was never changed. The same guest accepted native libcryptsetup mapper creation/removal, active swap, mounted filesystem and open-descriptor removal fences, and four process-loss reconciliation cases. This is not a power-loss or host reboot proof.

Review evidence is retained independently at docs/project/runtime/fr06c5e8-key-review-20260929T1212/. A blocked combined historical-evidence comparison was not replayed and is not counted as acceptance. A duplicate launch attempt rejected the existing vm-v1 directory; its already-completed result and exact copied source were reconciled instead of recreating or overwriting it.

Primary documentation: https://man7.org/linux/man-pages/man5/core.5.html and https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html.

A concurrent test-only change was reconciled in an independent review tree: both the actual child-process memory-lock-limit rejection and the mocked assertion that entropy is never requested after mlock failure are retained. No implementation change or native result was discarded.
