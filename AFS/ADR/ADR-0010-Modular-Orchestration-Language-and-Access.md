# ADR-0010: Modular Orchestration, Language and Controlled Expert Access

## Status
Accepted

## Decision
AIOS shall add orchestration, language, interaction and expert-session capabilities as separate packages connected through stable contracts. No package may directly mutate another package's internal state.

All expert sessions require explicit owner approval. Free project-staff access is quota-bound. Paid role access is quoted by role, project complexity and duration.

## Consequences
- Features can evolve independently.
- Integration failures are detected at contract and delivery gates.
- Text, voice, programming-language and human-language capabilities remain replaceable adapters.
- Commercial access cannot bypass owner authority.
