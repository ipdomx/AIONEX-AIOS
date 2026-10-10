# FR-09G — observed encrypted Docker-vault space preflight (2026-10-10)

**Status: SOURCE PREP ONLY. No load execution, production deployment, secret transfer, or data mutation.**

On the new production host nc-ph-4354, owner-provided Oct 10 console output showed root filesystem (~3.0 TB free, 9% used) and a distinct encrypted Docker/containerd runtime filesystem (63 GB total, ~23 GB free, 62% used). The FR-09 staging gate requires **at least 40 GiB available**. Quoting the host root free bytes as Docker runtime headroom would yield false-green admission.

The new read-only tool scripts/capacity/fr09_host_storage_preflight.py reads the host's actual root, Docker and containerd kernel filesystem counters and mount presence. It verifies the expected new hostname, distinct Docker-vault device, common Docker/containerd device and >= 40 GiB of available space on each. It refuses unmounted/missing storage, invalid numbers, old-host execution and misleading root-only claims. Offline negative tests cover these scenarios.

**Safe new-host check AFTER the source is reviewed and separately made available:**

    python3 /opt/AIOS/scripts/capacity/fr09_host_storage_preflight.py

The command only reads storage metadata and outputs JSON; status 0 means STORAGE_PRECHECK_PASS only, 2 means HOLD_STORAGE and 3 means failed observation. It does NOT verify FR-08 runtime acceptance, lab isolation, zero production credential reuse, provider egress disabled, or production health. Its output never authorizes starting a load test, mutating resources, provider calls, pruning images, stopping containers, altering LUKS or resizing volumes.

**Unresolved blocks:** current vault free bytes <40 GiB; FR-08 operating acceptance missing; no isolated full mixed 5,000 authenticated user lab with separate Postgres, Redis and isolated volumes; no complete 15-minute mixed run or exact provenance. Historical read-only 5,000-user passes are not FR-09 full acceptance.
