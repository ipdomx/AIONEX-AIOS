# FR-06D8C4B4 — Studio candidate process-reference scan

This source-only stage consumes the accepted C4B1 writer receipt, C4B2 runtime/backup-drain receipt, and one C4B3 cleanup candidate that requires removal of an owned staging name. It rechecks the exact current backend/studio-worker writer epoch, the backup-worker container identity and read-only Studio mount, and the Studio volume identity before touching candidate paths.

The candidate path is reopened from the Docker volume source through O_NOFOLLOW directory descriptors. The current staging identity must exactly match retained device/inode/type/uid/gid/mode/link-count/size evidence. For an owned-staging-only layout the final name must still be absent; for an owned staging+final hardlink layout both names must still match the retained same inode and link counts.

The host scan examines every numeric process thread for fd, cwd, root, exe, and mmap references to that exact staging device/inode. It performs two complete scans and revalidates the staging/final identity between and after the scans. Ambiguous disappearing proc entries, permission failures, writer epoch drift, backup-reader identity/mount drift, unexpected Studio mounts, initializer activity, path/identity drift, or any visible reference block the receipt.

A successful receipt may state candidate_reference_drain_verified=true and host_process_scan_verified=true, but process_drain_verified, cleanup_authorized, filesystem_mutation_performed, final_deletion_permitted, and full_host_closure remain false. The receipt is bound to the current boot id.

The source performs no kill/stop/restart, admission/database mutation, unlink/rename/write/chmod, execution settlement, retry, or final-file deletion.

Final local acceptance on this candidate: 27/27 focused process-reference tests passed and the complete repository suite passed 1874/1874. The focused suite now constructs and consumes the real C4B1 writer-epoch receipt, including the backup-reader identity/read-only-mount shape, so the B1→B4 contract is exercised directly. The earlier stacked-draft acceptance also recorded Ruff success. The current operator shell does not expose a Ruff executable, so no additional Ruff rerun is claimed; pytest and reporting acceptance are rerun on the final tree before commit.
