"""Small bounded local-model product brief and deterministic safe compiler input.

The Free/Ollama model never writes executable code. It supplies a short domain
brief that the reviewed source composer upgrades into a strict AIONEX product
specification. The strict schema and output evidence remain different from an
externally hosted model's full product JSON.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .controlled_project_builder import ControlledProjectBuilder
from .project_archetypes import infer_application_type


class CompactProjectSpecError(ValueError):
    """The bounded local model JSON does not meet the reviewed project contract."""


def compact_project_schema() -> dict[str, Any]:
    """Ollama-compatible JSON Schema with a deliberately short output surface."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "title", "tagline", "summary", "roles", "features", "records"],
        "properties": {
            "kind": {"type": "string", "enum": ["aionex.compact-project.v1"]},
            "title": {"type": "string", "minLength": 2, "maxLength": 100},
            "tagline": {"type": "string", "minLength": 5, "maxLength": 120},
            "summary": {"type": "string", "minLength": 20, "maxLength": 400},
            "roles": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": {"type": "string", "minLength": 2, "maxLength": 40},
            },
            "features": {
                "type": "array", "minItems": 3, "maxItems": 6,
                "items": {"type": "string", "minLength": 3, "maxLength": 110},
            },
            "records": {
                "type": "array", "minItems": 1, "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "fields"],
                    "properties": {
                        "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,39}$"},
                        "fields": {
                            "type": "array", "minItems": 1, "maxItems": 6,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["name", "type"],
                                "properties": {
                                    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,39}$"},
                                    "type": {"type": "string", "enum": ["string", "text", "integer", "number", "boolean", "email", "datetime"]},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def expand_compact_product_spec(raw: str, *, objective: str) -> dict[str, Any]:
    """Upgrade only a validated small brief into a reviewed deterministic archetype."""
    if not isinstance(raw, str) or not 2 <= len(raw) <= 12000:
        raise CompactProjectSpecError("compact brief is missing or too large")
    try:
        brief = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompactProjectSpecError("compact brief is not JSON") from exc
    schema = compact_project_schema()
    if not isinstance(brief, dict) or set(brief) != set(schema["required"]):
        raise CompactProjectSpecError("compact brief has an invalid key set")
    if brief["kind"] != "aionex.compact-project.v1":
        raise CompactProjectSpecError("compact brief version is invalid")
    for field, minimum, maximum in (
        ("title", 2, 100), ("tagline", 5, 120), ("summary", 20, 400),
    ):
        if not isinstance(brief[field], str) or not minimum <= len(brief[field].strip()) <= maximum:
            raise CompactProjectSpecError("compact textual field is invalid")
    roles = brief.get("roles")
    features = brief.get("features")
    records = brief.get("records")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 4:
        raise CompactProjectSpecError("compact role list is invalid")
    if not isinstance(features, list) or not 3 <= len(features) <= 6:
        raise CompactProjectSpecError("compact feature list is invalid")
    if not isinstance(records, list) or not 1 <= len(records) <= 3:
        raise CompactProjectSpecError("compact record list is invalid")
    if any(not isinstance(role, str) or not 2 <= len(role.strip()) <= 40 for role in roles):
        raise CompactProjectSpecError("compact role value is invalid")
    if any(not isinstance(x, str) or not 3 <= len(x.strip()) <= 110 for x in features):
        raise CompactProjectSpecError("compact feature value is invalid")
    # Every string goes through ControlledProjectBuilder._validate_spec for
    # anti-markup, URL/credential leakage, duplicate/reserved field and length checks.
    entities: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "fields"}:
            raise CompactProjectSpecError("compact record schema is invalid")
        name = record["name"]
        fields = record["fields"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name):
            raise CompactProjectSpecError("compact record name is invalid")
        if not isinstance(fields, list) or not 1 <= len(fields) <= 6:
            raise CompactProjectSpecError("compact record fields are invalid")
        normalized: list[dict[str, Any]] = []
        for i, field in enumerate(fields):
            if not isinstance(field, dict) or set(field) != {"name", "type"}:
                raise CompactProjectSpecError("compact record field is invalid")
            if not isinstance(field["type"], str) or field["type"] not in {"string", "text", "integer", "number", "boolean", "email", "datetime"}:
                raise CompactProjectSpecError("compact field type is invalid")
            normalized.append({"name": field["name"], "type": field["type"], "required": i == 0})
        entities.append({"name": name, "label": name.replace("_", " ").title(), "fields": normalized})
    clean_features = list(features)
    spec = {
        "schema_version": 3,
        "application_type": infer_application_type(objective, "universal_application"),
        "title": brief["title"],
        "tagline": brief["tagline"],
        "summary": brief["summary"],
        "audience": "Project members, reviewers and invited collaborators",
        "features": clean_features,
        "brand": {
            "primary": "#2563EB", "secondary": "#0891B2",
            "accent": "#F8FAFC", "surface": "#0F172A",
            "logo_concept": "Minimal project-specific geometric identity",
        },
        "architecture": {
            "frontend": "Responsive locally served application and accessible UI",
            "backend": "Reviewed local Python JSON API with input validation",
            "data": "SQLite transactional storage with bounded schema",
            "realtime": "Only explicit independently verified realtime features",
            "deployment": "Local standalone build with rollback archive; production activation requires approval",
        },
        "domain_blueprint": {
            "roles": roles,
            "entities": entities,
            "workflows": [{
                "name": "Create and review project record",
                "trigger": "Authorized member submits a validated record",
                "steps": [
                    "Validate supplied fields and member authorization",
                    "Persist through the reviewed local project API",
                    "Return the durable result and review state",
                ],
            }],
        },
        "sections": [
            {
                "id": "overview", "title": "Project overview",
                "body": "Review the project objective, audience and value before implementation.",
                "items": ["Project purpose and audience", "Key validated capabilities"],
            },
            {
                "id": "workflow", "title": "Reviewed user workflows",
                "body": "Follow supported project actions through validation and durable storage.",
                "items": ["Authorized record creation", "Review and persistence"],
            },
            {
                "id": "evidence", "title": "Verification and limitations",
                "body": "Inspect actual source, tests, rollback hashes and release conditions.",
                "items": ["Implementation test results", "Explicit approval blockers"],
            },
        ],
        "primary_action": "Open workspace",
        "secondary_action": "Review project evidence",
        "limitations": [
            "Cloud integrations, production publication and unreproduced tests require separate acceptance.",
        ],
    }
    try:
        return ControlledProjectBuilder._validate_spec(json.dumps(spec), objective=objective)
    except (ValueError, KeyError, TypeError) as exc:
        raise CompactProjectSpecError("compact product failed the strict reviewed compiler schema") from exc
