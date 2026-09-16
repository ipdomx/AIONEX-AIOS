# FR-06C4C1 — empty container-runtime-vault provisioning source

The production strategy keeps Docker and containerd configured at their standard paths. After a successful clean reconstruction, a guarded systemd oneshot binds encrypted `docker` and `containerd` subpaths over `/var/lib/docker` and `/var/lib/containerd` only after the vault host-ready verifier passes. If either bind fails, both are removed. The historical roots remain hidden underneath and untouched for rollback.

The repository ships fail-closed mount units and daemon gates as inert source. They are not installed by source merge or by empty-vault provisioning. Live installation belongs to C4C2 only after candidate runtime acceptance.

No historical runtime-copy command exists in this provisioning scope.
