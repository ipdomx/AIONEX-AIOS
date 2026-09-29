# FR-06C5E3 — Journal-bound configuration-file effects

## Scope and current status

Source integration of three filesystem steps with the C5E2 journal:
`install_swap_unit`, `install_tmp_unit`, and `disable_legacy_fstab`.
The implementation is `scripts/security/fr06c5_memory_config_files.py`.
Tests use private owned directory trees as a synthetic system root, as an
unprivileged user. No live `/etc`, swap, mapper, mount, systemd daemon, provider,
credential, Telegram bootstrap or production service is touched.

This is **not** the full C5E kernel adapter or a production activation command.
The source has no CLI and does not ship a production context reader. Its caller
must supply independently verified current source, boot, closed maintenance,
writer exclusion and bound host-state/preflight/boot-graph evidence. A typed
context returned by a test callback is not proof of those production conditions.
The C5E1 rendered unit text still describes a proposed boot arrangement; it is
not installed or enabled on the server by this part.

## Implemented behavior

- File preparation uses a create-only private operation bundle and one private
  staging directory on each target's filesystem. Root, target parent, staging,
  manifest and cooperating-operation lock identities are pinned. An existing
  unit is rejected rather than replaced. Partial staging is retained, never
  silently overwritten or cleaned up to enable retry.
- The immutable manifest binds original and staged file inode/device, mode,
  owner/group, link count, size, mtime and SHA-256. Every read checks identity,
  size, mtime and ctime before and after. atime is not content evidence; ctime
  cannot be part of a precomputed post-rename fingerprint because rename itself
  changes it. Current bytes are always hashed.
- Existing fstab is exchanged with its staged replacement using Linux
  `renameat2(RENAME_EXCHANGE)`. Its original inode remains in private staging;
  undo exchanges that exact inode back. New units are moved with
  `RENAME_NOREPLACE` and moved back on undo. No copy-over-original or unlink
  fallback is available. Missing syscall/filesystem support rejects the step.
- Both affected directories are fsynced after the rename. The C5E2 journal must
  already contain the exact durable pending intent before the adapter will run
  a file effect, even when called directly. Kernel/service step names are not
  accepted by this adapter.
- Before an effect, all three managed files must match their currently expected
  phase, not only the file being changed. A drifted earlier unit or later fstab
  therefore blocks a subsequent effect. Every final applied/restored result is
  independently checked again by the journal.
- Existing files with symlinks, multiple links, unsafe modes, unexpected owners,
  extended attributes, unbounded data or unstable reads are rejected. Extended
  attribute / SELinux / ACL preservation needs a separate reviewed contract;
  it is not silently stripped.
- The fstab transformation preserves unrelated bytes and the full original swap
  line behind an operation-specific comment. It rejects absent/duplicate legacy
  entries, additional swap devices, escaped/ambiguous paths, embedded NUL/CR and
  a previous operation marker. No active swap is disabled by this transformation.
- An observed mismatch after an exchange remains unknown. Neither filesystem
  helpers nor the journal delete an unexpected inode or manufacture an inverse
  operation. A cooperating lock does not exclude a malicious administrator or
  arbitrary noncooperating writer: proven writer exclusion is a prerequisite.

## Acceptance

74 directed cases execute as `nobody` with real Linux file operations.
They include 12 native process-interruption cases: three steps, both directions,
and a process killed before or after its rename. Only test-created child
processes are signalled. Reopened journals retain the pending intent; a repeated
apply/undo is rejected until read-only reconciliation. Explicit rollback returns
the original fstab content **and original inode, mode, owner/group and mtime**.

Additional cases cover both directory-sync failure and unsupported rename,
source/boot/generation/operation drift, short writes, private staging/name/parent
replacement, hard links, symlinks, permissions, preserved foreign inodes during a
race, persistent lock replacement across reopen, byte-identical replacement by
a different inode, and exact journal binding.

The first diagnostic run had one test expecting the adapter's narrower exception
instead of the transaction's public rejection type. It also could not write its
JUnit output because this newly created evidence parent was not traversable by
`nobody`. Both failures are retained; only the expectation and owned test-evidence
permissions were corrected. Application guards were not weakened. Ruff and Mypy
findings were corrected before final acceptance.

These tests prove process-crash behavior on the running test filesystem, **not
power-loss persistence, a host reboot, full-host drain, encrypted swap activation
or production writer exclusion**. Test context is explicitly synthetic.

## Primary implementation references

- Linux man-pages `rename(2)`: https://man7.org/linux/man-pages/man2/rename.2.html
- Linux man-pages `fsync(2)`: https://man7.org/linux/man-pages/man2/fsync.2.html

Atomic exchange and no-replace are distinct supported flags; neither is emulated
by an unsafe fallback. File and directory synchronization serve different roles.
Source/code verification is separate from the real host boot graph and rollout.

## Remaining before C5E / FR-06 closure

The accepted full-host-state cutover and live operation-bound writer exclusion
remain required. Kernel steps for backing/mapper identity, plaintext swapoff,
random-key encrypted swap activation, unit enable/reload and tmpfs mount must be
implemented and tested with actual postconditions and explicit recovery. The
file steps must then be composed into the complete ordered plan with a trusted
production context reader; no standalone file transaction authorizes that plan.
C5D provider/resource ambiguity, encrypted host-state transfer and C6 final
acceptance are not closed by this part. FR-07 remains complete. Previously
blocked provider inventory, post-D10 combined check and Telegram bootstrap tests
are not repeated.
