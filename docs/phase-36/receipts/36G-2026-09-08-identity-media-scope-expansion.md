# Phase 36G — Identity Media Scope Expansion — 2026-09-08

## Owner decision

The Owner expanded the current AIONEX creative-media contract to include governed identity media across **voice, image and video**, including voice cloning/transformation, face/avatar generation, face reenactment, face swap, talking-head generation and lip-sync. The scope must support free/local, external-free, paid and explicitly licensed catalog provider routes.

This expansion does **not** treat technical capability as rights authority. A provider or website allowing a celebrity/public-figure imitation is not itself evidence that AIONEX may lawfully market or deliver that identity. Real-person identity use remains fail-closed unless the user is the subject, the subject has consented, or a provider/rightsholder supplies a license that covers the requested operation and use scope.

## Governed identity classes

1. `self` — the user is the subject; checksum-bound rights/consent evidence is required before identity transformation/cloning is activated.
2. `consented_person` — another person has explicitly authorized the requested use; checksum-bound rights evidence is required.
3. `licensed_public_figure` — a public figure/artist identity is available through an explicitly licensed catalog/provider route. A durable license reference and checksum-bound evidence are mandatory. The route may identify the real person only inside the licensed scope.
4. `fictional_inspired` — a fictional or non-identical inspired persona. This path may use free or paid runtimes without real-person rights evidence, but it must not bind to a named real person or claim to be that person.

## Provider access classes

AIONEX records provider economics independently from identity rights:

- `local_free`
- `external_free`
- `paid`
- `licensed_catalog`

Free or paid status never substitutes for consent, publicity/likeness rights, a provider license or commercial-use authority.

## Internal enforcement added

`src/aios/phase36_identity_media.py` now provides a provider-neutral admission contract that:

- requires synthetic-media disclosure for every identity-media request;
- requires SHA-256-bound rights evidence for all real-person identity routes;
- requires a licensed-catalog route plus durable license reference for licensed public figures/artists;
- rejects a fictional/inspired request that names or claims a real person;
- requires explicit commercial-use authorization when commercial use is requested;
- returns only presence booleans for rights/license references in its public snapshot.

The source contract does not activate a provider. Provider/runtime acceptance remains a separate truth gate.

## Current launch policy for music and artist identity

The Owner approved original/instrumental/AI-generated music as the default current-launch path. Licensed/public-domain material remains admissible only when its rights evidence is real. Named-artist voice/face identity is not enabled merely because an external tool can generate it; it becomes eligible only through the `self`, `consented_person`, or `licensed_public_figure` governed identity classes.

## Truth boundary

This receipt expands product scope; it does not claim a live voice-clone, face-swap, avatar, talking-head or lip-sync provider has been accepted yet. Those runtime claims remain `specified` behind identity rights and runtime-acceptance gates until real provider/local execution evidence exists.
