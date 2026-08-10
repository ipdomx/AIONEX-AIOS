"""Project-aware deep validation planning for isolated Security Lab clones."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationScenario:
    id: str
    category: str
    objective: str
    requires_roles: tuple[str, ...] = ()
    requires_clone: bool = True
    mutation: bool = True
    evidence_required: tuple[str, ...] = ("request", "response", "terminal_state")


BASE_SCENARIOS: tuple[ValidationScenario, ...] = (
    ValidationScenario("auth-session-rotation", "authentication", "Verify login/logout/session rotation, revocation and stale-session rejection", ("user",)),
    ValidationScenario("authz-object-matrix", "authorization", "Verify cross-user object isolation and role boundaries", ("user_a", "user_b", "admin")),
    ValidationScenario("authz-privilege-boundary", "authorization", "Verify low-privilege identities cannot invoke owner/admin mutations", ("user", "admin", "owner")),
    ValidationScenario("input-contract-boundaries", "input-validation", "Exercise documented boundary, type and encoding cases without leaving the clone", ("user",)),
    ValidationScenario("file-upload-policy", "file-upload", "Verify MIME, extension, size, storage and retrieval policy with inert fixtures", ("user",)),
    ValidationScenario("rate-limit-abuse", "abuse-resistance", "Verify per-account and per-origin throttling using bounded request rates", ("user",)),
    ValidationScenario("business-state-replay", "business-logic", "Replay state-changing operations and confirm idempotency/terminal-state invariants", ("user", "admin")),
    ValidationScenario("financial-concurrency", "business-logic", "Verify balance/payment/refund transitions remain atomic under bounded concurrent clone requests", ("user", "admin")),
    ValidationScenario("api-object-authorization", "api-security", "Validate BOLA/IDOR boundaries for object identifiers discovered from the API contract", ("user_a", "user_b")),
    ValidationScenario("csrf-origin-boundary", "browser-security", "Verify unsafe cookie-authenticated requests reject foreign origins", ("user",)),
)


def build_scenario_plan(*, environment: str, available_roles: list[str] | None = None) -> dict[str, Any]:
    normalized = environment.strip().lower()
    if normalized != "security_clone":
        return {"admitted": False, "reason": "isolated-security-clone-required", "scenarios": []}
    roles = set(available_roles or [])
    scenarios = []
    for scenario in BASE_SCENARIOS:
        missing = sorted(set(scenario.requires_roles) - roles) if roles else list(scenario.requires_roles)
        scenarios.append({**asdict(scenario), "ready": not missing, "missing_roles": missing})
    return {"admitted": True, "reason": None, "scenarios": scenarios}


def authorization_matrix(roles: list[str], resources: list[str], actions: list[str]) -> list[dict[str, str]]:
    """Generate explicit test cells; expected decisions must come from project policy, not AI guesses."""
    result = []
    for role in sorted(set(roles)):
        for resource in sorted(set(resources)):
            for action in sorted(set(actions)):
                result.append({"role": role, "resource": resource, "action": action, "expected": "policy_required"})
    return result
