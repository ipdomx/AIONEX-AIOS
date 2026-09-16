# FR-06C4A — container runtime inventory and clean reconstruction contract

This subpart is read-only. It does not stop Docker/containerd, create the runtime vault, copy runtime stores, or change Cloudflare.

The live host currently carries a very large historical containerd content/snapshot store while the actual 36-container production topology uses only 17 unique images. The active-image logical set is about 7.51 GiB, so the accepted path is a clean encrypted runtime reconstruction inside a 64 GiB LUKS2 vault, not copying historical layers, snapshots, build cache, or Docker JSON logs.

Every currently-running image is bound to one of two authorities: an exact build from the protected repository or a digest-pinned external image. The candidate runtime must be rebuilt/pulled from those authorities before any live data-root switch. PostgreSQL, Redis, backup data and application asset data remain on the encrypted external vaults already established by earlier FR-06 subparts.

FR-06C4A authorizes no live cutover. C4B owns the isolated rehearsal and guarded provisioning/cutover source.
