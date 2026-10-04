# Phase 36 receipt — FR-11 Voice Transform pinned runtime source

Date: 2026-10-04
Scope: Voice Transform source/runtime wiring and VIP input contract.

This receipt records the Phase 36-owned source change for the governed
voice_transform capability.

The route is pinned to Replicate model adirik/hierspeechpp, version
ff5bcc71dc2c44662291fc348b9ca2eb40107c9f4b377b169fc0dea950c388c8.
The public provider schema requires input_sound and target_voice WAV inputs and
returns one generated-audio URI. The source sends the exact version through the
versioned prediction endpoint; it does not use mutable latest-model routing.

The runtime path remains governed by the existing Identity Media authority:
real-person target voices require the existing Owner grant plus rights evidence,
licensed-public-figure execution stays unavailable without licensed-catalog
authority, synthetic-media disclosure remains mandatory, and current authority
is rechecked across the provider boundary and before output persistence.

The VIP portal now collects separate source-content and target-voice WAV files,
including translated labels and validation across all six supported locales.

No live provider request, paid request, credential read, customer-data access or
Production deployment is part of this source receipt. Provider calls in tests
use httpx.MockTransport only. Operational acceptance and any real-output
provider canary remain separate gates.
