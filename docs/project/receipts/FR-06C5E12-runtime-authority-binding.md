# FR-06C5E12 — runtime activation-authority binding

This source part starts from protected main after PR #828 merge `8dba19d85e1f84f0d02c878ee39ae53044efa3c5`.

It adds a read/verify-only runtime binding between the short-lived C5E activation authority, the current source commit, host boot identity, the same closed maintenance operation/generation, the accepted full-host closure receipt, and the exact prerequisite evidence bytes named by the authority.

The verifier recomputes the activation and closure digests, rejects changed/reopened maintenance, rejects source or boot drift, rejects not-yet-valid or expired activation windows, and re-hashes the host-state, preflight and boot-graph evidence rather than trusting filenames. Success returns the existing typed `BoundContext` used by C5E journal adapters.

This part performs no swap, mount, mapper, loop, backing-file, systemd, Docker, provider, maintenance transition, reboot, or recovery effect. It is not the production activation operator and does not by itself satisfy writer quiescence, encrypted-swap runtime attestation, boot integration, C6 recovery, or FR-06 closure.

Focused local acceptance before PR: 91 tests passed across the new runtime-authority coverage, the existing activation-authority tests, and the existing memory-transaction journal tests. Protected CI remains authoritative for merge acceptance.
