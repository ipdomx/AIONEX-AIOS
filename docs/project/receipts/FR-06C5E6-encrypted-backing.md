# FR-06C5E6 — journal-bound encrypted backing creation

- Base: `ed4096d47e66feff3e120ae21ef9494925ea8e31`.
- Implements only `prepare_encrypted_backing` as a durable-intent-bound effect.
- Target is create-only, root/private in production semantics, fully allocated and descriptor-pinned; sparse/incomplete/replaced resources fail closed.
- Undo moves the exact owned inode into operation-private retained state; it does not unlink a re-resolved pathname.
- No loop, dm-crypt, key, mkswap, swapon, mount, systemd, production context reader or activation CLI is added here.
- Focused transaction/backing suite: 76 PASS. Ruff and Mypy pass. Production unchanged.
