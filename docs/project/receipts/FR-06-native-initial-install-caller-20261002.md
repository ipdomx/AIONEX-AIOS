# FR-06: native initial-install caller with independent signed admission

Source base: `3426e654e38da77a4e9705e6148cc809f189414b`, the existing PR835 review head. This change does not reconstruct the preparation/publication libraries or the integrated MCP2 timeout fix.

## Implemented path

`scripts/security/fr06_executor_native_install.py` adds the missing fixed-path caller for `install_unenrolled`, with `check` as its default CLI action and a separate explicit `install` action. It reads an independently provisioned owner Ed25519 public key and a short-lived signed permit, verifies the permit and retained control/history evidence, holds the permit-bound preexisting coordinator lock, reads actual clean local main and exact remote merged-PR/main identity, applies the existing app-bound protected-check validator, reads the safe maintenance authority projection and current boot identity, then invokes the existing file-publication transaction. The same native reader is called at each publisher authorization boundary.

No trust root, private/public key, permit, coordinator lock or external review is issued/provisioned by this caller. Its new signed-admission protocol is proposed source requiring review and independent operational setup; this receipt is NOT evidence that such setup or authorization exists. No second GitHub account is required or invented. A private signing key must not be given to this program or manufactured by an assistant to approve its own work.

## External trust boundary and non-claims

The owner-controlled trust root is fixed at `/etc/aionex/fr06-initial-install/owner-ed25519.pub`. A permit and exact evidence live under the fixed `/var/lib/aionex/fr06-initial-install-authority/<authorization UUID>/`. CLI arguments cannot substitute alternative keys, roots, source commits, callbacks or identities. Input files are bounded, canonical, private and no-follow, with exact file ownership, modes and link counts. Supporting evidence references must resolve to retained hash-matching canonical objects in that authorization directory; a bare hash is not accepted as an existing document.

The signature authenticates the independent review decision. It does NOT prove the substantive truth of historical no-effect claims, actual task fencing, or external provider outcomes. The independent issuer must establish those facts and preserve their evidence before signing. Signing synthetic fixture data, returning a Binding, editing task prompts, reading an old PID, or accepting a green CI run does not fulfill that operational obligation. This code provides no signer, historical reconciler, role-enrollment issuer or shortcut around the existing enrollment verifier.

Current production has no demonstrated owner trust key/permit/three-role initial-install control. The old unresolved runs are not reconciled by this source change. No historical terminal is created or rewritten. The caller still requires its exact accepted installed source, so it cannot install or authorize itself from a review worktree. An externally approved source/control transition remains necessary before live use.

## Native implementation and failure behavior

Public verification bytes are copied into sealed anonymous file descriptors and passed to fixed OpenSSL Ed25519 verification, without private-key access, temporary disk copies, inherited OpenSSL configuration, shell commands or raw diagnostic output. Only Ed25519 public-key encoding is accepted. OpenSSL 3.0 documents pure Ed25519 verification with `pkeyutl -verify -rawin`; reference: https://docs.openssl.org/3.0/man1/openssl-pkeyutl/ . Python file sealing uses the documented `os.memfd_create` and `fcntl.F_ADD_SEALS` interfaces.

The externally provisioned coordinator is never created or replaced. Its inode is checked against the signed permit; a separate real child must observe kernel lock contention. Name/inode/metadata are rechecked after that probe. Source and journal are sampled again after the database read. The permit is reverified after potentially slow reads so expiry during a check cannot grant a stale result. Supporting evidence, signature, trusted key and lock are also reread before return.

The publisher preserves its durable intents and rejects an existing or interrupted installation; the caller adds no automatic retry, rollback, adoption or cleanup. Both check and installation leave enrollment and production activation unauthorized. Any CLI error reports `admission_blocked_or_effect_uncertain` and `automatic_retry=false`, without claiming that prior effects did not occur. This cooperative control does not defend against a malicious root administrator or dishonest independently trusted signer.

## Actual tests and limitations

The new 87 directed cases passed under UID0. They use actual temporary Ed25519 key pairs, real OpenSSL verification, sealed descriptors, Git repositories, private file reads and competing kernel locks. A complete synthetic end-to-end case runs the real native reader, existing protected-check parser, preparation and file-publication implementation on disposable roots: check makes no target, installation creates only unenrolled files, and repetition is rejected without changing them. Remote GitHub responses, database authority, independent review content and the installed-path boundary are explicitly modeled; this is NOT real independent source approval or live role adoption.

Three controlled new-code drift tests first failed (source/journal changing during database reads, and lock-name replacement after a contention probe); the checks were corrected before acceptance. Those failed results are retained. Two separate fixture issues were corrected without weakening application checks: a simulated clock returned the wrong Python class, and a fake API router confused the rules endpoint with the branch endpoint.

Full-suite/nonroot results are not claimed by this paragraph; read the actual retained result and any later acceptance addition. No live key, permit, coordinator, installation, enrollment, source synchronization, MCP2 restart, service/provider operation, swap/tmp change or reboot has been performed by this work.

## Retained evidence

Interaction: `docs/project/runtime/fr06-recurring-task-health/interactive-native-install-20261002T120745344311Z-e1ff8728/`. Directed before/after XML is also retained in this isolated worktree's `docs/project/runtime/`. Existing PR835 checks apply only to their exact head, not to this new source until its protected checks actually run. FR06/C5D/C5E/C6 and the credential incident remain open; FR07 remains preserved.

## Complete nonroot acceptance

The corrected complete source export ran all **4150 tests successfully**, with zero failures/errors/skips and actual UID65534. Finished `2026-10-02T12:28:23.151045+00:00`; JUnitSHA256 `6031dd927059cfd1224db5b58316143dae645af0fe27fbae5d10a7fd56c7df11`. All2700 exported input files matched the working source before this documentation-only result addition. The new87 directed cases are included in4150, not additive. The independent key/signature and GitHub/DB/control decisions remain synthetic fixtures; no production authorization is inferred.

An earlier export omitted the tracked frontend source `web-dashboard/frontend/src/app/owner/secrets/page.tsx` because a broad exclusion confused the route name with secret storage. That caused two existing feature-inventory tests to fail (4148 passed). The exact Git blob for that UI source was verified and restored in a fresh export; no test or application code was changed and no credential data was copied. The failed XML/result remains retained. The successful artifacts are explicitly `full-suite-fixed.xml` and `full-suite-fixed-result.json`, not the first `full-suite.xml`.
