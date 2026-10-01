# FR-06 — require the official Debian liblzma security backport

Status: isolated source and OS-layer compatibility verification; merge/deployment HOLD remains in force.

## Scope and source authority

This change starts from the exact held PR #812 head `8e7174da3039a33e8886ad2febc779edde380c61`. It inherits the held #810/#811/#812 stack and is not permission to merge that stack, synchronize the live source, deploy, or close FR-06. The first current GitHub observation found four completed successful workflows and Final Validation still in progress on #812; that is not complete acceptance of the parent or this new head.

Debian's security tracker identifies `5.4.1-1+deb12u1` as affected by GHSA-5qpq-xqfv-j9pg (invalid write when a decoder is reinitialized after allocation failure), and `5.4.1-1+deb12u2` as fixed for Bookworm. Primary sources checked on 2026-09-30:

- https://security-tracker.debian.org/tracker/source-package/xz-utils
- https://security-tracker.debian.org/tracker/DLA-4783-1
- https://tukaani.org/xz/invalid-write-after-reinit.html

A read-only, disposable package simulation on an earlier retained Syft candidate found five pending Debian updates. It was discovery evidence on that older image, not an inventory of the final #812 image. The subsequent experiment used the exact #812 runtime OS-installation stanza and pinned Python base rather than treating the old Syft candidate as the current release.

## Change

Explicitly install `liblzma5` from the existing signed Debian repositories, require a package version at least `5.4.1-1+deb12u2`, and preserve its small documentation files so `dpkg --verify` can check every installed package file. No repository authentication bypass, scanner ignore rule, upstream source patch, broad distribution upgrade, compiler/module lock change, or live package installation was introduced.

The build now executes `verify_security_lzma.py` after `USER 1000:1000`. It checks installed package identity, architecture/status, Debian version floor, package-file integrity, the actual library mapped into Python, and its SHA-256. Nine finite synthetic cases exercise CRC32/CRC64/SHA256 XZ, legacy LZMA, streaming, corrupt/truncated/invalid inputs, and decoder memory limits.

These are **package-fix verification and compatibility cases**, not a reproduction of allocator-failure memory corruption, ASan, a check of every native consumer, or whole-image vulnerability acceptance.

## Retained verification

Evidence root: `/opt/AIOS/docs/project/runtime/fr06-os-package-review-20260930T1515`.

- Before the source correction, the new source contract failed while 23 other focused cases passed. This proves the installation-floor omission, not native exploitation.
- After the change, 114 combined targeted tests passed, including the 24 new cases and the existing PCRE2/Trivy contracts. The new cases are a subset, not an extra total.
- Two disposable OS-layer images were built from the original and corrected runtime package stanzas. They intentionally omit application dependencies and scanner binaries. They are **not** the full Security Lab image.
- The original OS-layer fixture was rejected specifically for its liblzma package version.
- The corrected fixture installed `5.4.1-1+deb12u2`, verified its package files and loaded library, and passed all nine native compatibility cases as UID 1000, with no capabilities, no network and a read-only root filesystem.
- Corrected library SHA-256: `5de60ec1bf90cd3d699188eb9ebb333c22b531394e0b030b55048edbd729ed17`.
- Full Root acceptance, source fingerprints and production metadata comparison are recorded independently in the evidence directory; GitHub checks must be evaluated on the actual published commit, not inherited from #812.

The initial optional quality command used nonexistent executables under `/opt/AIOS/.venv/bin`; those exit-127 setup failures are not quality passes. Any later quality result is recorded separately.

## Continuity and limits

A combined read of earlier full-image scan artifacts was blocked before execution and was not retried or rerouted. No prior blocked diagnostic was repeated. Consequently the previously reported 200 HIGH/CRITICAL instances (144 OS, 56 Go) remain historical retained evidence, not a newly measured count. This change does not claim to reduce that count, and no full-image or Trivy cold rebuild was performed in this part.

The production service set and live source are kept separate from the disposable experiments. FR-07 remains closed; FR-06, expanded capacity acceptance and final release remain open. No merge, auto-merge, deployment, host package upgrade, database/provider action, or production restart is authorized by this receipt.

## ملخص

أضيف شرط صريح لإصلاح Debian الرسمي لمكتبة liblzma5 بعد إثبات أن أوامر بناء النظام السابقة تبقي النسخة المتأثرة. نجح القبول المحدد على طبقة نظام معزولة واختبارات التوافق، دون ادعاء إعادة إنتاج عيب الذاكرة أو قبول الصورة الكاملة. التجميد والإطلاق غير المكتمل باقيان، ويُحفظ الاستكمال في التقرير الموحد.
