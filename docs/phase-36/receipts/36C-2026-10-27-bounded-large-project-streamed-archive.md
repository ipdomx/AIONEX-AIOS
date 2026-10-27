# Phase36C reviewed project delivery: bounded, disk-backed ZIP streaming

Date: 2026-10-27 UTC.
Project: AIONEX AIOS only.
Source baseline: 9b705c2309dce371014a6598c89acb033701d7bd.
Status: isolated source candidate, not deployed or release-approved.

## Actual fix

The old project download endpoint refused files beyond 50 MiB and created two complete ZIP copies in memory. The new flow preserves the original authentication, organization+project+execution scoped database SELECT, completed execution restriction, path containment and Owner approval receipt policy, while using an immediately unlinked tempfile instead of BytesIO. The ZIP is constructed and SHA-256 hashed using 1 MiB bounded file reads off the async event loop and then streamed in 1 MiB chunks with Content-Length and X-AIONEX-SHA256. A cancelled/finished request closes the file and releases its stream slot.

- 256 MiB maximum uncompressed retained project artifacts, 1000 ordinary files, 64 KiB Owner approval receipt.
- Two concurrent project ZIP archives per backend process; a further request waits at most 10 seconds before a transient 503 rather than indefinitely consuming resources.
- Strictly reject symlinks, hardlinks, special files, escaped directory entries, reserved generated owner-approval.json and changing file identity between stat/open. Files are opened with O_NOFOLLOW; no path from model output is executed.
- No ZIP/customer contents are logged and no customer database writes are performed by this endpoint. Separate statutory billing and account-level permissions are unchanged.

## Executed evidence

- 11 tests passed in independent disconnected Docker, including a genuinely over-legacy-size 51 MiB sparse asset, correct ZIP content and SHA256, bounded streaming bytes, stream cancellation releasing the concurrency slot, tenant-scoped 404, file count/size caps, approval receipt safety, symlink and hardlink protection.
- The real synthetic app+3D delivery package retained from the independently validated full integration was zipped without errors. Actual 76 entries included reviewed core Python source, real browser dist assets and screenshots for desktop/mobile/low-power. The CRC and independent byte-by-byte ZIP SHA256 comparison passed. No real customer data used.
- Production backend /tmp supports unlinked temporary files, but the candidate was not activated or tested with 5000 concurrent customer downloads. No production container restarted.
- No new project release approval is inferred by packaging a not-yet-approved generated project. FR08 owner/research release review, FR09 real 5000/15000 load and genuine 72h stability remain unaccepted. Physical cold-host recovery remains Owner-deferred to postlaunch only.

Test log SHA256: 4f2cfe87c0fdc01f537da6ea5c4cffbc3160a2eecd6459ef5259430365e274af
Actual 3D package proof: /mnt/aionex/fr09-isolated-lab-20261011/fr08-bounded-archive-test-20261027T2100Z/REAL-3D-PROJECT-ARCHIVE-STREAM-PROOF.json
Actual 3D package proof SHA256: a0fc572ccaff61d3d4c731e496b77ad66494e84ad9ac7463051ed67d6d2c17db

This is a source-level large-artifact export gate, not AIONEX AIOS final launch certification.
