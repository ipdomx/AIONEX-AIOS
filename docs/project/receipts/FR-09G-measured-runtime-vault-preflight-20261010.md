# FR-09G — New-host verified runtime capacity preflight (2026-10-10)

**State: SOURCE ONLY, NOT MERGED/DEPLOYED AT AUTHORING; 5,000-user full-mixed test NOT RUN.**

On NEW `nc-ph-4354` the owner measured `/` at roughly 3.0 TB free, but the **separate shared encrypted** `/var/lib/docker` + `/var/lib/containerd` runtime vault at only about **23 GiB available**. The 40 GiB heavy-work free-space prerequisite cannot be certified by supplying root filesystem free bytes. `--free-bytes` remains explicitly an operator-supplied staging budget, *not a live disk measurement*.

This source guard adds **read-only real filesystem-device + free-byte observation** for Docker and containerd. It measures both runtime paths (minimum free wins), verifies neither is silently falling back onto the root mount, and blocks `heavy_work_permitted` if a runtime path is unavailable, unverified or under 40 GiB. This does **not** touch the Docker daemon, LUKS, workloads, networking, customer content or the production filesystem. Failure to inspect paths is HOLD rather than synthetic PASS.

Offline regression tests prove that a 3 TB-free root alongside a 23 GiB-free Docker vault still fails the heavy-work gate; an unmounted vault aliasing the root is rejected; and missing measurement cannot authorize heavy work. The JSON explicitly reports `load_test_authorized=false` regardless of source-profile preflight outcome.

**Non-authorization:** Even measured storage and an FR-08 flag do not prove independently isolated lab resources, authentication, test images, no-provider/billing or owner-approved runtime limits. The 5,000-user load test remains blocked until a separate disposable backend/PostgreSQL/Redis and full safety admission are independently accepted. No docker-prune, deletion, rollover or deployment is part of this proposal.

**Shell contract:** the FR-09 profile CLI exits with status 2 for a HOLD (including an insufficient runtime vault or a weakened <40 GiB override), rather than returning exit 0 on a blocked preflight. Exit 0 certifies profile preflight only and never authorizes starting a load test.
