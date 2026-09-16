# FR-06C3D — local-backup production cutover closeout

The production `backup_data` domain was cut over to the encrypted mapper-backed `aionex-fr06-local-backup-vault` only after the guarded C3D executor merged and all exact-main checks passed. Backup Worker and Backend were drained, the legacy source was sealed read-only, an offline exact manifest copy completed, and both services returned on the candidate mount while admission remained closed and Cloudflare stayed unchanged.

The cutover exposed a real ownership mismatch in the provisioning contract: the backend image entrypoint drops Backup Worker to `aionex` uid/gid `1000:1000`, but the new backup subpath had been declared `root:root`. The runtime root was corrected to `1000:1000` mode `0700`, Backup Worker returned healthy, and PR #695 fixes the source contract and guard so future provision/unlock checks match the actual runtime user instead of weakening the worker.

A post-cutover encrypted platform backup completed locally and to R2 from the candidate storage, followed by an independent restore validation with both local and off-site validation true. The old `web-dashboard_backup_data` source remains retained read-only for rollback. Redis and host logs were not touched by C3D. FR-06 remains open and proceeds to C3E only after the owner hotfix is exact-main accepted.
