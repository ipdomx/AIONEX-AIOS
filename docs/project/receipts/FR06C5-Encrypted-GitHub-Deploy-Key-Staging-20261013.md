# FR06C5 — Correct the encrypted GitHub deploy identity without downtime

**Project:** AIONEX AIOS exclusively. **Host:** NEW `nc-ph-4354`. **Date:** 2026-10-13 UTC. **Source baseline:** protected `main` `de0123b72e761b6d1498a0d729cca88f53f5caca`.

## Actual defect, not presumed

The original C5 slot-3 legacy deployment identity file exists but is **zero bytes** (root-owned 0600) and cannot parse as an OpenSSH key. Nonetheless the existing MCP2 `_git_env()` selected it merely because `Path.is_file()` returned true and `server_status().deploy_key_exists` advertised it as available. A different AIOS-specific working GitHub deploy identity already exists; its SSH config pins the authentic GitHub host keys, and an independently checked `git ls-remote` against the exact `ipdomx/AIONEX-AIOS` repository succeeds on the current protected main.

**No private material is in this receipt, the branch, or test fixtures.**

## Concrete live-safe host staging performed

1. Root-only and no-follow file metadata checks confirmed the intended four-slot FR06C5 binder; slots 1 and 2 are already mounted from the LUKS host-state vault with `nodev,nosuid,noexec`.
2. An **existing authenticated AIOS GitHub deploy identity** was safely duplicated into **LUKS slot-3 encrypted vault storage**. This was a private, exact-byte verified, same-filesystem, atomic no-overwrite publication with 0600 permission, root owner, single hardlink count and fsync. Source identity remains unchanged.
3. Slot 4 already contains a separately valid 0600 encrypted AIOS cPanel identity, while its legacy target was missing. An **empty root-owned 0600 mount target file** was created in the legacy target location without placing any key bytes outside the vault or changing current SSH client configuration.
4. Both encrypted identities parse as genuine OpenSSH keys. A fresh **real GitHub SSH read** using the staged vault identity plus existing strict pinned host-key file succeeded and matched protected repository main `de0123b7...`.
5. No running Docker or MCP2 service was restarted; no live mount was added or removed, no other project touched and no IPMI/OLD action taken.

The real C5 four-path preflight now has all its filesystem source/target paths present, but the live four-slot *bind* remains `FR06C5_HOST_STATE_BIND_NOT_READY` (**not activated**) because the two private-key binds still require owner-approved safeguarded Docker-off maintenance. The original C5D guarded cutover has stricter source/rollback and operation-drain requirements; it must be reconciled with the existing active NS06 directory binds and an independently accepted recovery before execution. **Do not bypass this guard by mounting files during running Docker, and do not claim full FR06 acceptance.**

## Code-level fault correction

The proposed `ops/mcp2/server.py` change, without changing the existing 28 MCP tool API, now:
- Checks owner, permissions, hardlink/symlink, nonempty size and actual `ssh-keygen -y` parse result before offering an SSH identity; zero-byte legacy placeholders and forged nonempty files are refused.
- On NEW, prefers the LUKS-staged deploy identity while requiring a root-owned pinned known-hosts file and `StrictHostKeyChecking=yes`; no TOFU/accept-new on NEW.
- On legacy instance, preserves the former valid-key SSH mode for compatibility; never blindly injects caller-provided `GIT_SSH_COMMAND`.
- Makes `deploy_key_exists` truthful about a *usable parsed key*, or unknown on inaccessible metadata, not merely a file-name match.

**Tests:** Original MCP operator contracts **34/34 PASS**, plus six additional synthetic no-secret SSH key/source-selection regressions, **40/40 PASS**. An independently executed *real encrypted-key SSH GitHub read* also succeeded. Deployment of this new MCP source requires original protected CI followed by a bounded one-service update, **not** a Docker or customer-data restart.

## Separate deliberate no-network lab boundary

An additional attempt to build the exact protected main Backend in the encrypted FR09 **no-network** lab did not build: the lab daemon has no Docker bridge by **intentional admission policy** and BuildKit refused package installation with `network bridge not found`. No image was claimed. Do not alter the no-network FR09 daemon or borrow production network to convert this fail-closed test to fake green. Release-image construction must use an separately admitted network-capable build environment or a protected-CI signed OCI image artifact, followed by independent import/validation.

**Release status:** `FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED`; source staging success does not prove customer disaster recovery, guarded cold-boot, actual 5,000-user load, OCI/runtime deployment, or OLD disk archival acceptance.
