"""Phase 36L reusable sector packs over the universal Domain Blueprint v3 composer.

The packs are deterministic product/domain templates, not separate code forks.  They
reuse the governed universal project emitter and its local functional verification.
Sector-specific external authority (payments, licensed prescription review, public
records policy, etc.) remains an explicit gate rather than being simulated.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .controlled_project_builder import ControlledProjectBuildError, ControlledProjectBuilder

_ALLOWED_FIELD_TYPES = frozenset(
    {"string", "text", "integer", "number", "boolean", "datetime", "email", "url"}
)


@dataclass(frozen=True, slots=True)
class SectorField:
    name: str
    type: str
    required: bool = True

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", self.name):
            raise ValueError(f"invalid sector field: {self.name}")
        if self.type not in _ALLOWED_FIELD_TYPES:
            raise ValueError(f"unsupported sector field type: {self.type}")


@dataclass(frozen=True, slots=True)
class SectorEntity:
    name: str
    label: str
    fields: tuple[SectorField, ...]

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", self.name):
            raise ValueError(f"invalid sector entity: {self.name}")
        if not self.label.strip() or not 1 <= len(self.fields) <= 12:
            raise ValueError(f"invalid sector entity definition: {self.name}")
        names: set[str] = set()
        for field in self.fields:
            field.validate()
            if field.name in names or field.name in {"id", "created_at", "updated_at"}:
                raise ValueError(f"duplicate/reserved sector field: {field.name}")
            names.add(field.name)


@dataclass(frozen=True, slots=True)
class SectorWorkflow:
    name: str
    trigger: str
    steps: tuple[str, ...]

    def validate(self) -> None:
        if not self.name.strip() or not self.trigger.strip() or not 1 <= len(self.steps) <= 8:
            raise ValueError(f"invalid sector workflow: {self.name}")
        if any(not item.strip() for item in self.steps):
            raise ValueError(f"empty workflow step: {self.name}")


@dataclass(frozen=True, slots=True)
class SectorPack:
    key: str
    title: str
    objective: str
    audience: str
    roles: tuple[str, ...]
    entities: tuple[SectorEntity, ...]
    workflows: tuple[SectorWorkflow, ...]
    safety_boundaries: tuple[str, ...] = ()
    external_gates: tuple[str, ...] = ()

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,47}", self.key):
            raise ValueError("invalid sector pack key")
        if not 2 <= len(self.title.strip()) <= 100 or not 10 <= len(self.objective.strip()) <= 1000:
            raise ValueError("invalid sector pack text")
        if not 1 <= len(self.roles) <= 8 or len({x.casefold() for x in self.roles}) != len(self.roles):
            raise ValueError("sector roles must be unique and bounded")
        if not 1 <= len(self.entities) <= 12 or not 1 <= len(self.workflows) <= 12:
            raise ValueError("sector blueprint size is outside the reviewed bounds")
        entity_names: set[str] = set()
        for entity in self.entities:
            entity.validate()
            if entity.name in entity_names:
                raise ValueError(f"duplicate sector entity: {entity.name}")
            entity_names.add(entity.name)
        for workflow in self.workflows:
            workflow.validate()
        for text in (*self.safety_boundaries, *self.external_gates):
            if not text.strip():
                raise ValueError("empty sector safety/gate text")

    def domain_blueprint(self) -> dict[str, Any]:
        self.validate()
        return {
            "roles": list(self.roles),
            "entities": [
                {
                    "name": entity.name,
                    "label": entity.label,
                    "fields": [asdict(field) for field in entity.fields],
                }
                for entity in self.entities
            ],
            "workflows": [
                {
                    "name": workflow.name,
                    "trigger": workflow.trigger,
                    "steps": list(workflow.steps),
                }
                for workflow in self.workflows
            ],
        }

    def specification(self) -> dict[str, Any]:
        self.validate()
        limitations = [
            "This package is a governed local application baseline; live external integrations require their own credentials and approvals.",
            *self.safety_boundaries,
            *(f"External gate: {item}." for item in self.external_gates),
        ]
        feature_items = [workflow.name for workflow in self.workflows[:6]]
        for fallback in ("Tenant-scoped records", "Audit-ready workflow", "Deterministic local preview"):
            if len(feature_items) >= 3:
                break
            if fallback not in feature_items:
                feature_items.append(fallback)
        evidence_items = list(self.safety_boundaries[:2])
        evidence_items.extend(f"External gate: {item}" for item in self.external_gates[:2])
        for fallback in ("Local evidence retained", "External authority remains gated"):
            if len(evidence_items) >= 2:
                break
            if fallback not in evidence_items:
                evidence_items.append(fallback)

        return {
            "schema_version": 3,
            "application_type": "universal_application",
            "title": self.title,
            "tagline": f"Governed {self.title.lower()} operations without sector-specific code forks.",
            "summary": (
                f"A tenant-safe {self.title.lower()} reference application generated from the shared "
                "Domain Blueprint v3 composer with explicit workflow and activation boundaries."
            ),
            "audience": self.audience,
            "features": feature_items,
            "brand": {
                "primary": "#0F4C81",
                "secondary": "#0F766E",
                "accent": "#F8FAFC",
                "surface": "#07111F",
                "logo_concept": "A simple modular sector operations mark",
            },
            "architecture": {
                "frontend": "Responsive same-origin web administration and workflow interface",
                "backend": "Typed local API generated from reviewed domain entities",
                "data": "Transactional relational domain model with explicit audit-ready records",
                "realtime": "No realtime transport is required for the local reference acceptance",
                "deployment": "Local governed package only; external systems remain disabled until approved",
            },
            "domain_blueprint": self.domain_blueprint(),
            "sections": [
                {
                    "id": "overview",
                    "title": "Sector overview",
                    "body": "Review bounded roles, entities, and operational responsibilities.",
                    "items": [self.title, *self.roles[:3]],
                },
                {
                    "id": "workflow",
                    "title": "Governed workflows",
                    "body": "Execute the reference workflow locally before external integration.",
                    "items": [workflow.name for workflow in self.workflows[:4]],
                },
                {
                    "id": "evidence",
                    "title": "Evidence and activation boundaries",
                    "body": "Inspect deterministic source, local tests, safety boundaries, and external gates.",
                    "items": evidence_items,
                },
            ],
            "primary_action": "Review sector workflow",
            "secondary_action": "Inspect evidence",
            "limitations": limitations,
        }


@dataclass(frozen=True, slots=True)
class SectorBuildReceipt:
    key: str
    output_directory: Path
    domain_sha256: str
    file_count: int
    entity_count: int
    workflow_count: int
    targets: tuple[str, ...]
    tests: Mapping[str, Any]
    external_gates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "output_directory": str(self.output_directory),
            "domain_sha256": self.domain_sha256,
            "file_count": self.file_count,
            "entity_count": self.entity_count,
            "workflow_count": self.workflow_count,
            "targets": list(self.targets),
            "tests": dict(self.tests),
            "external_gates": list(self.external_gates),
        }


def _field(name: str, type_: str = "string", required: bool = True) -> SectorField:
    return SectorField(name, type_, required)


def _entity(name: str, label: str, *fields: SectorField) -> SectorEntity:
    return SectorEntity(name, label, tuple(fields))


def _workflow(name: str, trigger: str, *steps: str) -> SectorWorkflow:
    return SectorWorkflow(name, trigger, tuple(steps))


def _pack(
    key: str,
    title: str,
    objective: str,
    audience: str,
    roles: tuple[str, ...],
    entities: tuple[SectorEntity, ...],
    workflows: tuple[SectorWorkflow, ...],
    *,
    safety: tuple[str, ...] = (),
    gates: tuple[str, ...] = (),
) -> SectorPack:
    return SectorPack(key, title, objective, audience, roles, entities, workflows, safety, gates)


REFERENCE_SECTOR_PACKS: tuple[SectorPack, ...] = (
    _pack(
        "retail-supermarket",
        "Retail and Supermarket",
        "Build a retail store commerce web app and API for catalog, inventory, checkout orders, fulfillment, and reporting.",
        "Store operators, cashiers, inventory staff, and customers",
        ("customer", "cashier", "inventory_manager", "administrator"),
        (
            _entity("product", "Product", _field("sku"), _field("name"), _field("price", "number"), _field("active", "boolean")),
            _entity("stock_item", "Stock item", _field("sku"), _field("quantity", "integer"), _field("location")),
            _entity("order", "Order", _field("reference"), _field("status"), _field("total", "number")),
            _entity("inventory_event", "Inventory event", _field("sku"), _field("delta", "integer"), _field("reason")),
        ),
        (
            _workflow("Receive inventory", "inventory shipment arrives", "validate SKU", "record stock delta", "retain inventory event"),
            _workflow("Checkout order", "cashier submits cart", "validate products", "record order", "reserve stock", "return receipt state"),
            _workflow("Fulfill order", "paid-or-approved order is ready", "pick items", "record fulfillment", "close order"),
            _workflow("Inventory report", "manager requests report", "aggregate stock", "flag low inventory", "return report"),
        ),
        gates=("payment-provider-credential-for-live-charges",),
    ),
    _pack(
        "restaurant-hospitality",
        "Restaurant and Hospitality",
        "Build a restaurant web app and API for menus, reservations, orders, kitchen tickets, delivery status, and operations reporting.",
        "Guests, hosts, kitchen staff, delivery staff, and managers",
        ("guest", "host", "kitchen", "manager"),
        (
            _entity("menu_item", "Menu item", _field("name"), _field("price", "number"), _field("available", "boolean")),
            _entity("reservation", "Reservation", _field("guest_name"), _field("scheduled_at", "datetime"), _field("party_size", "integer")),
            _entity("food_order", "Food order", _field("reference"), _field("status"), _field("total", "number")),
            _entity("kitchen_ticket", "Kitchen ticket", _field("order_ref"), _field("status"), _field("notes", "text", False)),
        ),
        (
            _workflow("Reserve table", "guest requests a time", "validate availability", "record reservation", "return confirmation"),
            _workflow("Place order", "host submits order", "validate menu availability", "record order", "create kitchen ticket"),
            _workflow("Kitchen production", "ticket enters kitchen", "prepare items", "update ticket status", "mark ready"),
            _workflow("Delivery handoff", "order is ready for delivery", "assign handoff", "record status", "close delivery"),
        ),
        gates=("payment-provider-credential-for-live-charges", "delivery-provider-credential-if-enabled"),
    ),
    _pack(
        "pharmacy",
        "Pharmacy Administration",
        "Build a pharmacy inventory and prescription administration web app and API with licensed pharmacist review boundaries.",
        "Customers, licensed pharmacists, inventory staff, and auditors",
        ("customer", "pharmacist", "inventory_manager", "auditor"),
        (
            _entity("medication_item", "Medication item", _field("sku"), _field("name"), _field("stock", "integer"), _field("controlled", "boolean")),
            _entity("prescription_record", "Prescription record", _field("reference"), _field("status"), _field("received_at", "datetime")),
            _entity("dispense_request", "Dispense request", _field("prescription_ref"), _field("status"), _field("pharmacist_reviewed", "boolean")),
            _entity("stock_batch", "Stock batch", _field("sku"), _field("lot"), _field("quantity", "integer"), _field("expires_at", "datetime")),
        ),
        (
            _workflow("Prescription intake", "prescription record is received", "record reference", "mark pending pharmacist review", "retain audit state"),
            _workflow("Pharmacist review", "licensed pharmacist opens pending request", "verify administrative record", "record human decision", "release or reject request"),
            _workflow("Inventory update", "approved dispense is recorded", "validate stock batch", "record stock delta", "retain lot trace"),
        ),
        safety=(
            "The pack does not diagnose, prescribe, select treatment, or autonomously authorize dispensing.",
            "Any prescription/dispense release is human-reviewed by an appropriately authorized pharmacist in the deployment jurisdiction.",
        ),
        gates=("licensed-pharmacist-review", "jurisdictional-prescription-and-controlled-substance-policy"),
    ),
    _pack(
        "school-university",
        "School and University",
        "Build a school and university web app and API for admissions, courses, enrollments, student records, grading, and administration.",
        "Applicants, students, instructors, admissions staff, and administrators",
        ("applicant", "student", "instructor", "administrator"),
        (
            _entity("applicant", "Applicant", _field("name"), _field("email", "email"), _field("status")),
            _entity("course", "Course", _field("code"), _field("title"), _field("active", "boolean")),
            _entity("enrollment", "Enrollment", _field("student_ref"), _field("course_code"), _field("status")),
            _entity("student_record", "Student record", _field("student_ref"), _field("status"), _field("notes", "text", False)),
        ),
        (
            _workflow("Admissions", "applicant submits application", "validate application", "record review state", "notify administrative outcome"),
            _workflow("Course enrollment", "student requests course", "validate course", "record enrollment", "return timetable state"),
            _workflow("Grade record", "instructor submits grade", "validate authorization", "record grade event", "retain audit trail"),
            _workflow("Student administration", "administrator updates status", "validate role", "record change", "retain evidence"),
        ),
        gates=("student-data-residency-and-retention-policy",),
    ),
    _pack(
        "government-public-service",
        "Government Public Service",
        "Build a government public-service web app and API for cases, forms, approvals, service delivery, and immutable audit workflows.",
        "Residents, case workers, approvers, service administrators, and auditors",
        ("resident", "case_worker", "approver", "auditor"),
        (
            _entity("service_request", "Service request", _field("reference"), _field("service_type"), _field("status")),
            _entity("form_submission", "Form submission", _field("request_ref"), _field("form_type"), _field("submitted_at", "datetime")),
            _entity("approval_record", "Approval record", _field("request_ref"), _field("decision"), _field("decided_at", "datetime")),
            _entity("audit_entry", "Audit entry", _field("resource_ref"), _field("action"), _field("occurred_at", "datetime")),
        ),
        (
            _workflow("Submit public service", "resident submits a valid request", "validate form", "record case", "assign case worker"),
            _workflow("Case review", "case worker opens case", "review evidence", "request changes or forward", "retain review event"),
            _workflow("Approval", "authorized approver receives case", "verify authority", "record human decision", "publish administrative status"),
            _workflow("Audit", "auditor requests trace", "load case history", "verify event chain", "return redacted audit report"),
        ),
        safety=("No legal entitlement or public-authority decision is made autonomously by the software.",),
        gates=("agency-policy-and-records-retention-approval", "authorized-human-public-decision"),
    ),
    _pack(
        "logistics",
        "Logistics Operations",
        "Build a logistics web app and API for shipments, dispatch, warehouse state, delivery events, and operational reporting.",
        "Dispatchers, warehouse staff, drivers, customers, and managers",
        ("dispatcher", "warehouse", "driver", "manager"),
        (
            _entity("shipment", "Shipment", _field("reference"), _field("status"), _field("destination")),
            _entity("route", "Route", _field("shipment_ref"), _field("status"), _field("eta", "datetime", False)),
            _entity("warehouse_item", "Warehouse item", _field("sku"), _field("quantity", "integer"), _field("location")),
            _entity("delivery_event", "Delivery event", _field("shipment_ref"), _field("status"), _field("occurred_at", "datetime")),
        ),
        (
            _workflow("Dispatch shipment", "shipment is ready", "validate destination", "assign route", "record dispatch"),
            _workflow("Warehouse movement", "inventory moves", "validate SKU", "record movement", "update location"),
            _workflow("Delivery update", "driver submits status", "validate shipment", "record event", "update shipment state"),
        ),
        gates=("mapping-or-carrier-provider-credential-if-enabled",),
    ),
    _pack(
        "manufacturing",
        "Manufacturing Operations",
        "Build a manufacturing web app and API for work orders, materials, quality checks, maintenance tasks, and production reporting.",
        "Production planners, operators, quality staff, maintenance staff, and managers",
        ("planner", "operator", "quality", "manager"),
        (
            _entity("work_order", "Work order", _field("reference"), _field("status"), _field("quantity", "integer")),
            _entity("material", "Material", _field("sku"), _field("quantity", "number"), _field("unit")),
            _entity("quality_check", "Quality check", _field("work_order_ref"), _field("status"), _field("notes", "text", False)),
            _entity("maintenance_task", "Maintenance task", _field("asset_ref"), _field("status"), _field("scheduled_at", "datetime", False)),
        ),
        (
            _workflow("Schedule work order", "planner releases work", "validate materials", "record work order", "assign production state"),
            _workflow("Record production", "operator reports progress", "validate work order", "record quantity", "update status"),
            _workflow("Quality review", "batch reaches inspection", "record inspection", "human quality decision", "release or hold batch"),
            _workflow("Maintenance", "asset requires maintenance", "record task", "assign technician", "close with evidence"),
        ),
        safety=("Safety-critical machine actuation is outside this administrative pack and requires separate industrial controls certification.",),
        gates=("industrial-control-and-machine-safety-validation-if-actuation-enabled",),
    ),
    _pack(
        "real-estate",
        "Real Estate Administration",
        "Build a real-estate web app and API for properties, listings, applications, lease requests, maintenance, and human review.",
        "Applicants, agents, property managers, owners, and auditors",
        ("applicant", "agent", "property_manager", "auditor"),
        (
            _entity("property", "Property", _field("reference"), _field("status"), _field("address", "text")),
            _entity("listing", "Listing", _field("property_ref"), _field("status"), _field("price", "number")),
            _entity("application", "Application", _field("listing_ref"), _field("applicant_ref"), _field("status")),
            _entity("lease_request", "Lease request", _field("application_ref"), _field("status"), _field("reviewed", "boolean")),
        ),
        (
            _workflow("Publish listing", "agent prepares listing", "validate property", "record listing", "publish local status"),
            _workflow("Submit application", "applicant submits application", "validate fields", "record application", "queue human review"),
            _workflow("Lease review", "manager reviews application", "verify authority", "record human decision", "retain audit evidence"),
        ),
        safety=("Tenant-selection, lending, legal, and regulated eligibility decisions remain human-reviewed and jurisdiction-specific.",),
        gates=("housing-and-consumer-protection-policy-review",),
    ),
    _pack(
        "professional-services",
        "Professional Services",
        "Build a professional-services web app and API for client matters, evidence records, deliverables, review, and administration.",
        "Clients, professionals, reviewers, and administrators",
        ("client", "professional", "reviewer", "administrator"),
        (
            _entity("matter", "Matter", _field("reference"), _field("status"), _field("summary", "text")),
            _entity("evidence_record", "Evidence record", _field("matter_ref"), _field("source"), _field("checksum")),
            _entity("deliverable", "Deliverable", _field("matter_ref"), _field("status"), _field("version", "integer")),
            _entity("review_record", "Review record", _field("deliverable_ref"), _field("decision"), _field("reviewed_at", "datetime")),
        ),
        (
            _workflow("Matter intake", "client request arrives", "validate scope", "record matter", "assign professional"),
            _workflow("Evidence record", "professional adds evidence", "record source", "bind checksum", "retain provenance"),
            _workflow("Deliverable review", "draft is ready", "route to reviewer", "record human decision", "release or request changes"),
        ),
        safety=("Regulated professional advice remains subject to qualified human review and applicable professional rules.",),
        gates=("qualified-professional-review-when-regulated",),
    ),
)


def compose_custom_sector(
    *,
    key: str,
    title: str,
    objective: str,
    audience: str,
    roles: tuple[str, ...],
    entities: tuple[SectorEntity, ...],
    workflows: tuple[SectorWorkflow, ...],
    safety_boundaries: tuple[str, ...] = (),
    external_gates: tuple[str, ...] = (),
) -> SectorPack:
    """Create an unlisted sector through the same Domain Blueprint v3 contract."""
    if key in {item.key for item in REFERENCE_SECTOR_PACKS}:
        raise ValueError("custom sector key collides with a reference pack")
    pack = SectorPack(
        key,
        title,
        objective,
        audience,
        roles,
        entities,
        workflows,
        safety_boundaries,
        external_gates,
    )
    pack.validate()
    return pack


def build_sector_reference(pack: SectorPack, output_root: Path) -> SectorBuildReceipt:
    """Render and locally verify one sector without any external provider request."""
    pack.validate()
    destination = output_root.resolve() / pack.key
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o700)
    source = destination / "source"
    source.mkdir(mode=0o700)

    raw_spec = pack.specification()
    spec = ControlledProjectBuilder._validate_spec(  # noqa: SLF001 - shared governed emitter
        json.dumps(raw_spec, ensure_ascii=False), objective=pack.objective
    )
    domain_payload = json.dumps(
        spec["domain_blueprint"], ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    planning_digest = hashlib.sha256(
        ("phase36l:" + pack.key).encode("utf-8")
    ).hexdigest()
    planning: dict[str, Any] = {
        "manifest_sha256": planning_digest,
        "provider": "local-deterministic-sector-pack",
        "model": None,
        "departments": [],
    }
    files = ControlledProjectBuilder._render_files(  # noqa: SLF001
        pack.title, pack.objective, spec, planning
    )
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(content, encoding="utf-8")

    tests = ControlledProjectBuilder._test_source(  # noqa: SLF001
        source, pack.title, spec
    )
    if not bool(tests.get("passed")):
        raise ControlledProjectBuildError(
            f"sector reference failed deterministic verification: {pack.key}"
        )
    profile = json.loads((source / "PROJECT_PROFILE.json").read_text(encoding="utf-8"))
    actual_domain = (source / "DOMAIN_BLUEPRINT.json").read_text(encoding="utf-8")
    actual_digest = hashlib.sha256(actual_domain.encode("utf-8")).hexdigest()
    expected_digest = str(profile.get("domain_blueprint_sha256") or "")
    if actual_digest != expected_digest:
        raise ControlledProjectBuildError("sector domain blueprint digest mismatch")
    # Check the canonical blueprint produced by the pack still normalizes to the same data.
    if json.loads(actual_domain) != json.loads(domain_payload):
        raise ControlledProjectBuildError("sector domain blueprint changed during rendering")
    file_count = sum(1 for path in source.rglob("*") if path.is_file())
    receipt = SectorBuildReceipt(
        key=pack.key,
        output_directory=destination,
        domain_sha256=actual_digest,
        file_count=file_count,
        entity_count=len(pack.entities),
        workflow_count=len(pack.workflows),
        targets=tuple(str(item) for item in profile.get("targets") or ()),
        tests=tests,
        external_gates=pack.external_gates,
    )
    (destination / "SECTOR_RECEIPT.json").write_text(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
