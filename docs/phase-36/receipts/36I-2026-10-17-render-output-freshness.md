# Phase 36I / FR16C — fresh candidate output directories

Date: 2026-10-17  
Base: `6a22bc2e81a715a1b2faf93e05b216f1c8cfce48`

## Problem and change

The candidate runner could accept stale artifacts after a zero-exit subprocess, follow an output symlink and write a success manifest through a symlink. All three behaviors were reproduced using explicitly synthetic local byte fixtures and a mocked renderer.

The corrected runner atomically reserves a new private destination for every run, rejects existing directories and destination links, and creates its script and manifest exclusively. Output inspection rejects links and non-regular files, verifies each opened file's identity during hashing, and closes its descriptor on every path. Fresh regular outputs retain matching size/hash metadata and the existing artifact schema.

**Usage contract:** pass a destination that does not yet exist. Empty pre-created directories and the workspace root itself are rejected. The constructor/render signatures, `preflight()`, scene `_script()`, relative output filenames and artifact fields remain unchanged. No production caller was found in the repository search.

## Verification and retained evidence

On NEW, the existing Python 3.11.2 test environment executed the 16 added boundary cases and existing candidate, interactive foundation and asset pipeline tests: **33 passed in 0.39s**. Full repository CI retains its original Python 3.12 configuration.

Original source SHA-256: `7f4fc35687e6f5d5183dbce0a9eed322fd095bbe0860243146740ef96f3823f4`.

Corrected source SHA-256: `27c07d6659acf2404df68d2b97401dfcfc1285a46ccb19a59b469363f2337c08`.

The original four candidate tests and the scene script remain unchanged. Independent review checked the final descriptor-closing implementation and the behavior change.

See [the project receipt](../../project/receipts/FR09-FR16-evidence-admission-20261017.md) for exact reproduction results, source hashes, test commands and retained evidence paths.

## Acceptance scope

The tests use synthetic bytes and mocked Blender subprocesses. They establish output freshness and each file's identity at inspection time. They do not establish valid GLB/PNG content, a real rendered scene, a joint atomic seal against a continuing same-permission writer, or kernel/resource isolation. The existing historical Phase 36I render receipt remains historical evidence.

Hunyuan remains quarantined. Current renderer/browser acceptance and the full FR16 parent batch remain open.
