# FR-06C4C2 — clean container-runtime reconstruction and cutover contract

The new runtime is built from authorities, not copied from the old runtime. Ten active images are rebuilt from the exact protected source and seven external images are pulled by digest. The candidate runtime may be prebuilt using separate daemon sockets/state, but it must not start application containers before the live cutover window.

The five authoritative encrypted volumes are re-registered in the clean Docker metadata. Runtime caches, model cache, PostgreSQL socket and Coturn transient state are recreated cleanly. No historical containerd content/snapshots, Docker BuildKit cache, or JSON logs are copied.

During cutover Docker/containerd stop first, encrypted bind mounts cover their standard data roots, fail-closed gates start the daemons, and the exact previously-running topology is recreated. The hidden legacy underlays remain untouched for rollback; no candidate-to-legacy layer reverse copy is ever allowed.
