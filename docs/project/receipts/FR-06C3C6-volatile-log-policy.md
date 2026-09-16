# FR-06C3C6 — volatile host-log boundary

The current host retains persistent journald and rsyslog output on the unencrypted root. C3E therefore cannot close after Redis alone.

The selected forward policy mounts `/var/log` itself as a bounded 1 GiB tmpfs with `nodev,nosuid,noexec`, and forces journald to `Storage=volatile`. This is stronger than only disabling rsyslog because direct file writers also land on volatile storage. Rsyslog may remain enabled for compatibility, but its files are then inside tmpfs.

Source merge does **not** install or activate either file. Production activation is a later guarded C3E operation: first retain required historical logs inside the encrypted operations vault, quiesce rsyslog, switch/restart journald to volatile mode, mount tmpfs on `/var/log`, recreate expected directories with systemd-tmpfiles, restart rsyslog, enable the mount for boot, and verify the live mount and runtime journal path. The old root-filesystem bytes are treated as residual remanence because FR-06 does not claim full-disk encryption or secure erasure of historical blocks.
