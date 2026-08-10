"""Evidence-gated AIONEX Security Genome and Rule Forge."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AuditEvent, SecurityFinding, SecurityRule, SecurityRuleValidation, uuid_str
from app.services import adaptive_intelligence, knowledge_learning


def now() -> datetime:
    return datetime.now(UTC)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _detector_for(finding: SecurityFinding) -> tuple[str, dict[str, Any]]:
    evidence = dict(finding.evidence or {})
    if finding.source == "aionex-headers" and finding.title.startswith("Missing "):
        header = finding.title.removeprefix("Missing ").strip().lower()
        return "http-header", {"kind": "missing_header", "header": header}
    if finding.category == "csp" and evidence.get("directive"):
        return "http-header", {"kind": "csp_forbidden_directive", "directive": str(evidence["directive"]).lower()}
    if finding.source in {"aionex-source", "aionex-secrets"} and evidence.get("marker"):
        return "source-pattern", {"kind": "source_marker", "marker": str(evidence["marker"]), "category": finding.category}
    if finding.source == "nuclei" and evidence.get("template_id"):
        return "nuclei-reference", {"kind": "nuclei_template", "template_id": str(evidence["template_id"])}
    if finding.source == "aionex-api-contract":
        return "api-contract", {"kind": "api_contract", "category": finding.category, "title": finding.title}
    return "aionex-policy", {"kind": "finding_fingerprint", "source": finding.source, "category": finding.category, "title": finding.title}


def _trust_from_finding(finding: SecurityFinding) -> float:
    score = float(finding.confidence or 0.0)
    if finding.state == "confirmed": score += 0.12
    if finding.evidence: score += 0.05
    return round(min(0.90, max(0.0, score)), 4)


async def derive_candidate(session: AsyncSession, actor: UserRecord, finding: SecurityFinding) -> SecurityRule:
    if actor.role != "Super Owner":
        raise PermissionError("Only the Super Owner can promote Security Genome candidates")
    if finding.organization_id != actor.organization_id or finding.state != "confirmed":
        raise ValueError("Only confirmed findings can produce rule candidates")
    rule_type, detector = _detector_for(finding)
    signature = hashlib.sha256(canonical({"type": rule_type, "detector": detector}).encode()).hexdigest()
    existing = await session.scalar(select(SecurityRule).where(SecurityRule.organization_id == actor.organization_id, SecurityRule.signature == signature))
    if existing is not None:
        return existing
    rule = SecurityRule(
        id=uuid_str(), organization_id=actor.organization_id, source_finding_id=finding.id, created_by_id=actor.id,
        rule_type=rule_type, name=f"AIONEX: {finding.title}"[:240], signature=signature, detector=detector,
        status="quarantine", trust_score=_trust_from_finding(finding), validation_passes=0, validation_failures=0,
    )
    session.add(rule)
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id, action="security.rule.candidate_created", resource_type="security_rule", resource_id=rule.id, details={"source_finding_id": finding.id, "rule_type": rule_type, "trust_score": rule.trust_score}))
    await session.flush()
    return rule


def evaluate_detector(detector: dict[str, Any], sample: dict[str, Any]) -> bool:
    kind = detector.get("kind")
    if kind == "missing_header":
        headers = {str(k).lower(): str(v) for k, v in dict(sample.get("headers") or {}).items()}
        return str(detector.get("header") or "").lower() not in headers
    if kind == "csp_forbidden_directive":
        value = str(sample.get("csp") or "").lower()
        return str(detector.get("directive") or "").lower() in value
    if kind == "source_marker":
        markers = {str(value) for value in sample.get("markers") or []}
        return str(detector.get("marker") or "") in markers
    if kind == "nuclei_template":
        return str(sample.get("template_id") or "") == str(detector.get("template_id") or "")
    if kind == "api_contract":
        return str(sample.get("category") or "") == str(detector.get("category") or "") and str(sample.get("title") or "") == str(detector.get("title") or "")
    if kind == "finding_fingerprint":
        return str(sample.get("source") or "") == str(detector.get("source") or "") and str(sample.get("category") or "") == str(detector.get("category") or "")
    return False


def validation_corpus(detector: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    kind = detector.get("kind")
    if kind == "missing_header":
        header = str(detector["header"]); return ({"headers": {}}, {"headers": {header: "present"}})
    if kind == "csp_forbidden_directive":
        directive = str(detector["directive"]); return ({"csp": f"script-src 'self' '{directive}'"}, {"csp": "script-src 'self'"})
    if kind == "source_marker":
        marker = str(detector["marker"]); return ({"markers": [marker]}, {"markers": ["safe-marker"]})
    if kind == "nuclei_template":
        template = str(detector["template_id"]); return ({"template_id": template}, {"template_id": "different-template"})
    if kind == "api_contract":
        positive = {"category": detector.get("category"), "title": detector.get("title")}; return (positive, {"category": "safe", "title": "safe"})
    return ({"source": detector.get("source"), "category": detector.get("category")}, {"source": "different", "category": "different"})


async def validate_candidate(session: AsyncSession, actor: UserRecord, rule: SecurityRule, *, corpus_id: str = "aionex-generated-v1") -> SecurityRule:
    if actor.role != "Super Owner" or rule.organization_id != actor.organization_id:
        raise PermissionError("Only the Super Owner can validate Security Genome rules")
    positive, negative = validation_corpus(dict(rule.detector or {}))
    passed = evaluate_detector(rule.detector, positive) and not evaluate_detector(rule.detector, negative)
    session.add(SecurityRuleValidation(id=uuid_str(), rule_id=rule.id, outcome="passed" if passed else "failed", corpus_id=corpus_id, evidence={"positive_detected": evaluate_detector(rule.detector, positive), "negative_detected": evaluate_detector(rule.detector, negative)}))
    if passed:
        rule.validation_passes += 1
        rule.trust_score = round(min(1.0, rule.trust_score + 0.08), 4)
        if rule.validation_passes >= 1 and rule.validation_failures == 0 and rule.trust_score >= 0.80:
            rule.status = "validated"
    else:
        rule.validation_failures += 1
        rule.trust_score = round(max(0.0, rule.trust_score - 0.25), 4)
        rule.status = "quarantine"
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id, action="security.rule.validated" if passed else "security.rule.validation_failed", resource_type="security_rule", resource_id=rule.id, details={"corpus_id": corpus_id, "trust_score": rule.trust_score}))
    return rule


async def promote_rule(session: AsyncSession, actor: UserRecord, rule: SecurityRule) -> SecurityRule:
    if actor.role != "Super Owner" or rule.organization_id != actor.organization_id:
        raise PermissionError("Only the Super Owner can promote Security Genome rules")
    if rule.status != "validated" or rule.trust_score < 0.80 or rule.validation_failures:
        raise ValueError("Rule has not met the Security Genome promotion gate")
    rule.status = "promoted"; rule.promoted_at = now()
    item = await knowledge_learning.ingest_item(
        session, actor, scope_type="organization", scope_id=actor.organization_id,
        namespace="security-genome", subject=rule.name,
        content={"rule_id": rule.id, "rule_type": rule.rule_type, "detector": rule.detector, "signature": rule.signature},
        content_text=f"Verified security detection rule: {rule.name}. Type: {rule.rule_type}.",
        confidence=rule.trust_score, tags=["security", "rule", "genome"],
        provenance=[{"source": f"security-rule:{rule.id}", "source_type": "security_scan", "source_quality": rule.trust_score, "direct_evidence": True}],
    )
    await knowledge_learning.verify_item(session, actor, item, accepted=True, confidence=rule.trust_score, note="Promoted from validated Security Genome rule")
    session.add(AuditEvent(organization_id=actor.organization_id, user_id=actor.id, action="security.rule.promoted", resource_type="security_rule", resource_id=rule.id, details={"knowledge_item_id": item.id, "trust_score": rule.trust_score}))
    return rule
