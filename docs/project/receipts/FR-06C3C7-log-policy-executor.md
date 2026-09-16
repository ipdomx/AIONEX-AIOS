# FR-06C3C7 — guarded volatile-log activation

This source-only executor activates the already-reviewed C3C6 log boundary later in C3E. It is intentionally separate from Redis cutover: Redis can be recovered without changing host logging, and logging can be rolled back without copying or mutating Redis AOF.

The apply path requires a retained C3E Redis closeout plus an operations-vault host-ready check and fresh protected-main evidence. It stops rsyslog before changing mounts, installs only repository-pinned systemd sources, restarts journald into volatile mode, mounts `/var/log` on tmpfs, recreates standard log directories and restarts rsyslog. The final acceptance verifies the live filesystem and service state.

Rollback removes only files whose SHA-256 still matches the executor-installed repository sources. It never deletes the old root-filesystem log underlay and never claims secure erase of historical blocks. FR-06 protects active selected storage domains; full-disk historical remanence remains outside that claim.
