"""Passive OpenAPI contract analysis for authentication and authorization gaps."""

from __future__ import annotations

import hashlib
from typing import Any

_MUTATING = {"post", "put", "patch", "delete"}
_ID_NAMES = {
    "id",
    "user_id",
    "project_id",
    "workspace_id",
    "organization_id",
    "order_id",
    "payment_id",
    "resource_id",
}
_PUBLIC_HINTS = {
    "/auth/login",
    "/auth/register",
    "/auth/forgot",
    "/health",
    "/ready",
    "/portal",
}


def _fingerprint(path: str, method: str, marker: str) -> str:
    return hashlib.sha256(f"openapi|{method}|{path}|{marker}".encode()).hexdigest()


def analyze_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        return {"scanner": "aionex-api-contract-v1", "operations": 0, "findings": []}
    global_security = spec.get("security")
    operations = 0
    for path, raw_path in paths.items():
        if not isinstance(raw_path, dict):
            continue
        raw_path_parameters = raw_path.get("parameters")
        path_parameters: list[Any] = (
            raw_path_parameters if isinstance(raw_path_parameters, list) else []
        )
        for method, operation in raw_path.items():
            method_lower = str(method).lower()
            if method_lower not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
            } or not isinstance(operation, dict):
                continue
            operations += 1
            security = operation.get("security", global_security)
            likely_public = any(
                str(path).startswith(prefix) for prefix in _PUBLIC_HINTS
            )
            if (
                method_lower in _MUTATING
                and not likely_public
                and (security is None or security == [])
            ):
                findings.append(
                    {
                        "source": "aionex-api-contract",
                        "category": "api-authentication",
                        "title": "Mutating API operation has no declared security requirement",
                        "severity": "high",
                        "confidence": 0.72,
                        "state": "observed",
                        "fingerprint": _fingerprint(
                            str(path), method_lower, "no-security"
                        ),
                        "cwe": "CWE-306",
                        "owasp": "API2:2023",
                        "location": f"{method_lower.upper()} {path}",
                        "evidence": {"method": method_lower.upper(), "path": path},
                        "remediation": "Require authenticated access at the server boundary and document the security scheme in the API contract.",
                    }
                )
            parameters: list[dict[str, Any]] = []
            raw_operation_parameters = operation.get("parameters")
            operation_parameters: list[Any] = (
                raw_operation_parameters
                if isinstance(raw_operation_parameters, list)
                else []
            )
            for candidate in [*path_parameters, *operation_parameters]:
                if isinstance(candidate, dict):
                    parameters.append(candidate)
            object_param = any(
                str(item.get("in") or "") == "path"
                and (
                    str(item.get("name") or "").lower() in _ID_NAMES
                    or str(item.get("name") or "").lower().endswith("_id")
                )
                for item in parameters
            )
            raw_responses = operation.get("responses")
            responses: dict[str, Any] = (
                raw_responses if isinstance(raw_responses, dict) else {}
            )
            if object_param and not likely_public and "403" not in responses:
                findings.append(
                    {
                        "source": "aionex-api-contract",
                        "category": "object-authorization",
                        "title": "Object-scoped API contract does not document a forbidden response",
                        "severity": "low",
                        "confidence": 0.45,
                        "state": "observed",
                        "fingerprint": _fingerprint(
                            str(path), method_lower, "object-authz-contract"
                        ),
                        "cwe": "CWE-639",
                        "owasp": "API1:2023",
                        "location": f"{method_lower.upper()} {path}",
                        "evidence": {
                            "method": method_lower.upper(),
                            "path": path,
                            "documented_responses": sorted(map(str, responses)),
                        },
                        "remediation": "Verify object-level authorization in implementation and document 403/404 behavior in the API contract.",
                    }
                )
    raw_components = spec.get("components")
    components: dict[str, Any] = (
        raw_components if isinstance(raw_components, dict) else {}
    )
    raw_schemes = components.get("securitySchemes")
    schemes: dict[str, Any] = raw_schemes if isinstance(raw_schemes, dict) else {}
    if not schemes:
        findings.append(
            {
                "source": "aionex-api-contract",
                "category": "api-authentication",
                "title": "OpenAPI contract declares no security schemes",
                "severity": "medium",
                "confidence": 0.65,
                "state": "observed",
                "fingerprint": _fingerprint("*", "*", "no-security-schemes"),
                "cwe": "CWE-306",
                "owasp": "API2:2023",
                "location": "openapi.components.securitySchemes",
                "evidence": {"operations": operations},
                "remediation": "Declare the production authentication scheme and apply it to protected operations.",
            }
        )
    return {
        "scanner": "aionex-api-contract-v1",
        "operations": operations,
        "findings": findings,
    }
