# Phase 36J — primary GLB integrity at delivery

Date: 2026-10-20 UTC
Scope: FR16 admission and copying of the primary GLB in each logical model group.
Status: implementation, independent source review and focused offline tests passed; protected CI is a separate gate.

## Problem

The primary model used weaker file handling than the LOD variants added in PR #948.
Resolving its path before checking for a symlink accepted links inside the staging
root. Primary admission also accepted noncanonical paths and converted declared
sizes to integers. Copying reopened the source with an unrestricted file copy.

An offline reproduction against merged main
b91157e433e491af586eed9d03f13f6a4a9654cb admitted an in-root file symlink,
directory symlink, hardlink, double-slash path and numeric-string size.
The regression suite now rejects these cases.

## Changes

- Share canonical relative path, SHA-256 and strictly typed size validation
  between primary models and their LOD variants.
- Bound primary models by the existing desktop per-asset budget of 24 MiB.
- Read through directory handles without following symlinks. Require a regular
  file with one link, verify size and identity before and after the bounded read,
  and verify the content digest and embedded GLB resource boundary.
- Retain staging-root and relative-path provenance for staged models and the
  records produced by the existing Tripo generator.
- Repeat validation immediately before copying and create output exclusively.
  Set permissions on the open descriptor. An existing output remains intact.
- Preserve valid nested legacy models, uppercase GLB suffixes and digests,
  embedded data resources, existing metadata and defaults, and generated models
  without LOD variants.

## Verification

The exact isolated-worktree run passed **116 tests** in **2.55 seconds**, with
no failures or skips:

    PYTHONPATH=src PROJECT_3D_AUTOGEN_ENABLED=false \
      /opt/AIOS/.venv/bin/python -B -m pytest -q \
      tests/test_fr16_primary_asset_integrity.py \
      tests/test_fr16_lod_delivery.py \
      tests/test_phase36_autonomous_3d_full_project.py

The 65 new cases cover invalid evidence, links and special files, malformed or
externally referenced GLBs, mutation after admission, revalidation of evidence
before copying, and exclusive output. Positive cases exercise the real
blueprint/copy functions. The real Tripo record-producing function is tested
using a local fake client and an empty key, followed by the actual copy path.

Independent source review found no blocking issue in the bounded diff. The
service and test files tested here have SHA-256:

- Service: 8cd0c0a4bc478bb9df0044ec229082cd48d6de4f0280e756b50479370bf2fb4d
- New tests: 21f49a54aa99d1d05b6af1c13b398c19dc7644d6081118d80f08c22c3daf62fd

## Acceptance boundary

This is bounded input and copy validation, not a full glTF conformance check.
These offline tests do not attest a provider request, a fresh generated-product
build, browser/device performance, optimizer integration or production deployment.

The earlier PR #948 build/browser evidence remains a separate preserved result.
Production workers and the NS12 observer are outside this source change.
Full FR16, authenticated current-generation recovery, durable worker recovery,
the natural 72-hour observation, actual 5000-user capacity and full release
remain open.
