# FR-06 — bounded diagnostics for failed pinned build steps

Date: 2026-09-30. Parent: `814ba235c67d84f58b6251c3199a09b5fdaa489a` (#814).
State: **HOLD — isolated source correction; no merge, deployment or live-source synchronization.**

## What the previously inaccessible job log establishes

The completed Production Docker Build job `109956966528` for PR #813 / run `36735779890` failed in `gitleaks-builder`, at `go mod download all`. The helper raised `Pinned build step failed; retained log: download.log`. Grype and Syft were canceled subsequently. This is not evidence of a liblzma verification failure, a Trivy timeout, or failure of those canceled stages.

The detailed child-process output was written only inside the unsuccessful build stage. The job's diagnostics upload reported no files. The exact reason for the historical download failure therefore remains unproven: do not label it a proxy outage, checksum failure, or transient condition without the missing evidence.

The general `gh run view --log-failed` route was still unavailable while other jobs ran. The completed job log was read through the documented `gh api` interface, captured into a non-terminal pipe and emitted only as JSON-escaped text. No terminal control sequence was executed or directly rendered. This is distinct from the blocked production-inventory request, which was not repeated. Official CLI reference: https://cli.github.com/manual/gh_api .

## Correction and limits

The shared pinned-build `run` helper now emits a fixed-schema `AIONEX_BUILD_FAILURE` JSON summary before preserving its original failure or timeout. It reports the exit code or timeout, total log size, bounded bytes examined, tail SHA-256 and fixed error-category labels. Categories are observations of at most the final 64 KiB, not independently established root causes or authorization to retry.

No raw log text, command arguments, environment values, URL, or filesystem path is included in that summary. It reads the already-owned open file descriptor rather than reopening a replaceable path. The complete original child output remains in the existing private build log. Successful steps remain silent. Exclusive creation and existing exception behavior are retained.

No retries, fallback proxy, checksum exceptions, compiler/module changes, workflow changes, test reductions, or timeout increases were added. Download, verification, upstream tests, binary checksums and scanner rules remain required. Shared consumers receive diagnostics through their existing helper import; no unrelated process-management semantics were changed.

## Evidence

- A real failing subprocess reproduced the missing-summary defect on the parent before the patch.
- The corrected helper and existing Gitleaks contracts passed 61 focused tests as `nobody`. This includes native subprocess failure, timeout, success, control-character/credential non-disclosure, invalid-byte logs, bounded-tail reading, and replaced-path isolation. These are not upstream Gitleaks detector tests or a full-image vulnerability scan.
- Full Root source-copy validation and quality results are retained independently under `/opt/AIOS/docs/project/runtime/fr06-build-failure-diagnostics-20260930/`; exact-head CI acceptance remains separate.
- The first local stage build stopped at CLI argument validation because the host's legacy builder did not support `--progress`. No Dockerfile stage began in that attempt. A subsequent standalone-stage preparation request was blocked before execution and was not retried or rerouted. No local native stage-build acceptance is claimed.
- The production-inventory command was blocked before execution. No fresh container identity/health comparison is claimed for this continuation. No deployment, container restart, live-source update, secret access, or provider operation was requested.

The historical 200 HIGH/CRITICAL image findings are not remeasured by this work. FR-06 and full release stay open; FR-07 retains its recorded closure. Parent PRs remain held and unmerged; no auto-merge is enabled.
