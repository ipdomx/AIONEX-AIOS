# 36N / FR-03C4 — remove unused ujson dependency

The proposed `ujson` 6 major upgrade was reviewed against actual production usage. No production backend source, script, `src/`, or project test imports the package, so the direct `ujson==5.13.0` runtime pin is removed instead of upgrading an unused library.

Acceptance proves the full backend dependency set resolves without it, `ujson` is not pulled transitively, the standard FastAPI/Pydantic JSON serialization path remains valid, the new absence contract passes, Core passes 957/957, and the runtime dependency audit reports no known vulnerabilities.

No production mutation is authorized by this receipt. Protected GitHub checks and the consolidated FR-03C rollout remain mandatory.
